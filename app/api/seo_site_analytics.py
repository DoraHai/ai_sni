"""Operator-managed, site-scoped analytics and export settings."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, PositiveInt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.module_workspace import SeoSite
from app.models.seo_site_analytics import SeoSiteAnalyticsSource, SeoSiteAnalyticsMonthly, SeoSiteExportTemplate
from app.security.auth import AuthContext
from app.seo_demo_source import get_seo_session as get_session, require_seo_scoped_auth as require_scoped_auth
from app.seo_publication_export import BEIJING, DEFAULT_PUBLICATION_LIST_TEMPLATE, public_template_columns
from app.seo_site_analytics import (AnalyticsError, ProviderClient, normalize_config,
    public_source, save_secrets, secrets_of, validate_month,
    validate_service_account, validate_source, validate_template, pull_site_month, fetch_provider)

router = APIRouter()


def error(status, code, message):
    return HTTPException(status, {"code": code, "message": message})


async def scope(session, ctx, tenant_id, site_id, edit=False):
    ctx.ensure_tenant(tenant_id)
    if not (ctx.can_edit("seo.site") if edit else ctx.can_view("seo.site")):
        raise error(403, "forbidden", "需要网站编辑权限" if edit else "需要网站查看权限")
    site = await session.get(SeoSite, site_id)
    if site is None or site.tenant_id != tenant_id:
        raise error(404, "site_not_found", "SEO 网站不属于当前客户")
    return site


async def source_row(session, tenant_id, site_id, source, *, lock=False):
    validate_source(source)
    query = select(SeoSiteAnalyticsSource).where(SeoSiteAnalyticsSource.tenant_id == tenant_id,
        SeoSiteAnalyticsSource.site_id == site_id, SeoSiteAnalyticsSource.source == source)
    return await session.scalar(query.with_for_update() if lock else query)


class SourceUpdate(BaseModel):
    tenant_id: PositiveInt
    site_id: PositiveInt
    source: str
    enabled: bool = True
    config: dict[str, Any]
    secrets: dict[str, Any] = {}
    clear_secrets: list[str] = []


@router.get("/site/analytics-sources")
async def sources(tenant_id: PositiveInt, site_id: PositiveInt, session: AsyncSession = Depends(get_session),
                  ctx: AuthContext = Depends(require_scoped_auth)):
    await scope(session, ctx, tenant_id, site_id)
    rows = (await session.scalars(select(SeoSiteAnalyticsSource).where(
        SeoSiteAnalyticsSource.tenant_id == tenant_id, SeoSiteAnalyticsSource.site_id == site_id))).all()
    return {"items": [public_source(row) for row in rows]}


@router.put("/site/analytics-sources")
async def save_source(req: SourceUpdate, session: AsyncSession = Depends(get_session),
                      ctx: AuthContext = Depends(require_scoped_auth)):
    await scope(session, ctx, req.tenant_id, req.site_id, True)
    try:
        config = normalize_config(req.source, req.config)
        row = await source_row(session, req.tenant_id, req.site_id, req.source, lock=True)
        if row is None:
            row = SeoSiteAnalyticsSource(tenant_id=req.tenant_id, site_id=req.site_id, source=req.source,
                created_by=ctx.user_id)
            session.add(row)
        secret = secrets_of(row)
        previous_mode = (row.config or {}).get("mode") if row.config else None
        allowed = {"service_account_json"} if req.source == "ga4" else {"secret_key", "refresh_token", "access_token", "access_token_expires_at"}
        if any(key not in allowed for key in req.clear_secrets) or any(key not in allowed for key in req.secrets):
            raise AnalyticsError("invalid_secret", "凭证字段无效")
        for key in req.clear_secrets:
            secret.pop(key, None)
        for key, value in req.secrets.items():
            if value in (None, ""):
                continue
            secret[key] = validate_service_account(value) if key == "service_account_json" else str(value).strip()
        if req.source == "baidu_tongji":
            if previous_mode and previous_mode != config["mode"]:
                for key in (("secret_key", "refresh_token", "access_token", "access_token_expires_at")
                            if config["mode"] == "business" else ("access_token", "access_token_expires_at")):
                    if key not in req.secrets:
                        secret.pop(key, None)
            if previous_mode and previous_mode != config["mode"] or any(
                req.secrets.get(key) for key in ("secret_key", "refresh_token")
            ):
                if not req.secrets.get("access_token"):
                    secret.pop("access_token", None)
                    secret.pop("access_token_expires_at", None)
            if config["mode"] == "business" and config.get("token_entered_at"):
                try:
                    row.token_expires_at = datetime.fromisoformat(config["token_entered_at"].replace("Z", "+00:00")) + timedelta(days=30)
                except ValueError as exc:
                    raise AnalyticsError("invalid_expiry", "Token 填写日期无效") from exc
            elif config["mode"] == "account" and secret.get("access_token_expires_at"):
                row.token_expires_at = datetime.fromisoformat(secret["access_token_expires_at"])
            else:
                row.token_expires_at = None
        row.config = config
        row.enabled = req.enabled
        row.updated_by = ctx.user_id
        row.last_test_at = row.last_test_status = row.last_test_message = None
        save_secrets(row, secret)
        await session.commit()
        return public_source(row)
    except AnalyticsError as exc:
        raise error(422, exc.code, str(exc)) from exc


class ScopedRequest(BaseModel):
    tenant_id: PositiveInt
    site_id: PositiveInt


@router.delete("/site/analytics-sources/{source}")
async def delete_source(source: str, tenant_id: PositiveInt, site_id: PositiveInt,
                        session: AsyncSession = Depends(get_session), ctx: AuthContext = Depends(require_scoped_auth)):
    await scope(session, ctx, tenant_id, site_id, True)
    try:
        row = await source_row(session, tenant_id, site_id, source)
    except AnalyticsError as exc:
        raise error(422, exc.code, str(exc)) from exc
    if row:
        await session.delete(row)
        await session.commit()
    return {"deleted": bool(row)}


class ExchangeRequest(ScopedRequest):
    code: str


@router.post("/site/analytics-sources/baidu_tongji/oauth/exchange")
async def exchange_baidu(req: ExchangeRequest, session: AsyncSession = Depends(get_session),
                         ctx: AuthContext = Depends(require_scoped_auth)):
    await scope(session, ctx, req.tenant_id, req.site_id, True)
    row = await source_row(session, req.tenant_id, req.site_id, "baidu_tongji", lock=True)
    if row is None or row.config.get("mode") != "account":
        raise error(409, "baidu_not_configured", "请先保存百度账号 API Key 和 Secret Key")
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            secret = await ProviderClient(http).exchange(row.config, secrets_of(row), req.code.strip())
        save_secrets(row, secret)
        row.token_expires_at = datetime.fromisoformat(secret["access_token_expires_at"])
        await session.commit()
        return {"message": "百度账号授权成功", "source": public_source(row)}
    except (AnalyticsError, KeyError) as exc:
        raise error(400, getattr(exc, "code", "baidu_auth_failed"), str(exc) if isinstance(exc, AnalyticsError) else "请先填写 Secret Key") from exc


@router.post("/site/analytics-sources/{source}/test")
async def test_source(source: str, req: ScopedRequest, session: AsyncSession = Depends(get_session),
                      ctx: AuthContext = Depends(require_scoped_auth)):
    await scope(session, ctx, req.tenant_id, req.site_id, True)
    try:
        row = await source_row(session, req.tenant_id, req.site_id, source, lock=True)
        if row is None:
            raise AnalyticsError("not_configured", "请先保存数据源配置")
        now = datetime.now(timezone.utc)
        yesterday = (now.astimezone(BEIJING).date() - timedelta(days=1)).isoformat()
        failure = None
        try:
            async with httpx.AsyncClient(timeout=20) as http:
                uv, pv, _ = await fetch_provider(ProviderClient(http), row, yesterday, yesterday, test=True)
            row.last_test_status = "ok"
            row.last_test_message = (f"连接成功，昨日 UV {uv} / PV {pv}" if uv is not None or pv is not None
                                     else "连接成功，昨日无数据") if source == "ga4" else "连接成功"
        except AnalyticsError as exc:
            failure = exc
            row.last_test_status, row.last_test_message = "failed", str(exc)
        row.last_test_at = now
        await session.commit()
        if failure:
            raise error(400, failure.code, str(failure))
        return public_source(row)
    except AnalyticsError as exc:
        raise error(422, exc.code, str(exc)) from exc


class PullRequest(ScopedRequest):
    month: str
    source: str | None = None


def monthly_payload(row):
    return {key: getattr(row, key) for key in ("source", "month", "uv", "pv", "status", "error_code",
        "error_message", "fetched_at", "raw_meta", "last_error_code", "last_error_message", "last_attempt_at")}


@router.post("/site/analytics/pull")
async def pull_month(req: PullRequest, session: AsyncSession = Depends(get_session),
                     ctx: AuthContext = Depends(require_scoped_auth)):
    await scope(session, ctx, req.tenant_id, req.site_id, True)
    try:
        results = await pull_site_month(session, tenant_id=req.tenant_id, site_id=req.site_id,
            month=req.month, source=req.source, fetched_by=ctx.user_id)
        return {"items": [monthly_payload(row) for row in results]}
    except AnalyticsError as exc:
        raise error(422, exc.code, str(exc)) from exc


@router.get("/site/analytics/monthly")
async def monthly(tenant_id: PositiveInt, site_id: PositiveInt, from_month: str | None = None, to_month: str | None = None,
                  from_alias: str | None = Query(None, alias="from"), to_alias: str | None = Query(None, alias="to"),
                  session: AsyncSession = Depends(get_session), ctx: AuthContext = Depends(require_scoped_auth)):
    await scope(session, ctx, tenant_id, site_id)
    try:
        from_month, to_month = from_month or from_alias, to_month or to_alias
        if not from_month or not to_month:
            raise AnalyticsError("invalid_month", "请填写起始和结束月份")
        validate_month(from_month)
        validate_month(to_month)
        if from_month > to_month:
            raise AnalyticsError("invalid_month", "起始月份不能晚于结束月份")
    except AnalyticsError as exc:
        raise error(422, exc.code, str(exc)) from exc
    rows = (await session.scalars(select(SeoSiteAnalyticsMonthly).where(
        SeoSiteAnalyticsMonthly.tenant_id == tenant_id, SeoSiteAnalyticsMonthly.site_id == site_id,
        SeoSiteAnalyticsMonthly.month >= from_month, SeoSiteAnalyticsMonthly.month <= to_month)
        .order_by(SeoSiteAnalyticsMonthly.month.desc(), SeoSiteAnalyticsMonthly.source))).all()
    return {"items": [monthly_payload(row) for row in rows]}


@router.get("/site/publications/export-template")
async def get_template(tenant_id: PositiveInt, site_id: PositiveInt, session: AsyncSession = Depends(get_session),
                       ctx: AuthContext = Depends(require_scoped_auth)):
    await scope(session, ctx, tenant_id, site_id)
    row = await session.get(SeoSiteExportTemplate, site_id)
    row = row if row and row.tenant_id == tenant_id else None
    return {"columns": public_template_columns(row.columns if row else None),
            "is_default": row is None, "available": list(DEFAULT_PUBLICATION_LIST_TEMPLATE)}


class TemplateUpdate(ScopedRequest):
    columns: list[dict]


@router.put("/site/publications/export-template")
async def put_template(req: TemplateUpdate, session: AsyncSession = Depends(get_session),
                       ctx: AuthContext = Depends(require_scoped_auth)):
    await scope(session, ctx, req.tenant_id, req.site_id, True)
    try:
        columns = validate_template(req.columns)
    except AnalyticsError as exc:
        raise error(422, exc.code, str(exc)) from exc
    row = await session.get(SeoSiteExportTemplate, req.site_id)
    if row is None:
        row = SeoSiteExportTemplate(site_id=req.site_id, tenant_id=req.tenant_id)
        session.add(row)
    row.columns, row.updated_by = columns, ctx.user_id
    await session.commit()
    return {"columns": columns, "is_default": False}


@router.delete("/site/publications/export-template")
async def delete_template(tenant_id: PositiveInt, site_id: PositiveInt, session: AsyncSession = Depends(get_session),
                          ctx: AuthContext = Depends(require_scoped_auth)):
    await scope(session, ctx, tenant_id, site_id, True)
    row = await session.get(SeoSiteExportTemplate, site_id)
    if row and row.tenant_id == tenant_id:
        await session.delete(row)
        await session.commit()
    return {"columns": public_template_columns(), "is_default": True}
