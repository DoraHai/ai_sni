"""Authenticated, site-scoped HTTP access to SEO page captures."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, PositiveInt
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_factory
from app.models.module_workspace import SeoSite
from app.models.seo import SeoContentAsset, SeoContentPublication, SeoSitePage
from app.models.seo_page_capture import SeoPageCapture
from app.module_scope import seo_site_is_operational
from app.security.auth import AuthContext
from app.seo_demo_source import get_seo_session as get_session, require_seo_scoped_auth as require_scoped_auth
from app.seo_page_capture import CaptureError, PageCaptureService, _check_url, capture_storage_path
from app.seo_serp import canonical_url, domain_matches

router = APIRouter()
logger = logging.getLogger(__name__)
_COOLDOWN = timedelta(seconds=60)


class CaptureCreate(BaseModel):
    tenant_id: PositiveInt
    site_id: PositiveInt
    url: str
    relation_type: Literal["site_page", "publication"] | None = None
    relation_id: PositiveInt | None = None


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def _deadline() -> datetime:
    # Covers the renderer's own timeout plus dispatch and DB settling.
    return datetime.now(timezone.utc) - timedelta(seconds=get_settings().seo_page_capture_timeout_seconds + 60)


async def _expire_stale(session: AsyncSession, tenant_id: int, site_id: int) -> None:
    await session.execute(
        update(SeoPageCapture)
        .where(SeoPageCapture.tenant_id == tenant_id, SeoPageCapture.site_id == site_id,
               SeoPageCapture.status.in_(("pending", "running")),
               SeoPageCapture.captured_at < _deadline())
        .values(status="failed", error_code="timeout")
    )


async def _site(session: AsyncSession, tenant_id: int, site_id: int) -> SeoSite:
    site = await session.get(SeoSite, site_id)
    if site is None or site.tenant_id != tenant_id:
        raise _error(404, "site_not_found", "SEO 网站不属于当前客户")
    return site


async def _capture(session: AsyncSession, tenant_id: int, capture_id: int,
                   *, allow_stale_update: bool = True) -> SeoPageCapture:
    row = await session.get(SeoPageCapture, capture_id)
    if row is None or row.tenant_id != tenant_id:
        raise _error(404, "capture_not_found", "截图不存在")
    await _site(session, tenant_id, row.site_id)
    if allow_stale_update:
        await _expire_stale(session, tenant_id, row.site_id)
        await session.commit()
        await session.refresh(row)
    return row


def _primary_source(request: Request) -> bool:
    decision = getattr(request.state, "seo_data_source_decision", None)
    return getattr(decision, "source", "primary") == "primary"


def _discard_image(result) -> None:
    if result is None or not result.storage_key:
        return
    try:
        capture_storage_path(get_settings().seo_page_capture_storage_dir, result.storage_key).unlink(missing_ok=True)
    except (OSError, ValueError):
        logger.warning("Could not remove discarded SEO capture image")


@lru_cache(maxsize=1)
def _capture_service() -> PageCaptureService:
    # Share the service's semaphore among HTTP background tasks in this process.
    return PageCaptureService()


def _payload(row: SeoPageCapture) -> dict:
    return {name: getattr(row, name) for name in (
        "id", "tenant_id", "site_id", "relation_type", "relation_id", "source_url", "status",
        "error_code", "final_url", "http_status", "redirect_chain", "warnings",
        "viewport_width", "viewport_height", "image_width", "image_height", "sha256", "captured_at",
    )}


async def _relation(session: AsyncSession, tenant_id: int, site_id: int, url: str,
                    relation_type: str | None, relation_id: int | None) -> tuple[str, int]:
    if (relation_type is None) != (relation_id is None):
        raise _error(422, "invalid_relation", "relation_type 和 relation_id 必须同时提供")
    if relation_type is None:
        # An omitted relation means one exact URL match in this site's page inventory.
        pages = list(await session.scalars(select(SeoSitePage).where(
            SeoSitePage.tenant_id == tenant_id, SeoSitePage.site_id == site_id, SeoSitePage.url == url,
        ).limit(2)))
        if len(pages) != 1:
            raise _error(422, "site_page_required", "请指定站内页面，或提供唯一匹配的页面 URL")
        return "site_page", pages[0].id
    if relation_type == "site_page":
        page = await session.get(SeoSitePage, relation_id)
        if page is None or page.tenant_id != tenant_id or page.site_id != site_id:
            raise _error(404, "relation_not_found", "站内页面不属于当前网站")
        if canonical_url(page.url) != canonical_url(url):
            raise _error(422, "relation_url_mismatch", "截图 URL 与站内页面 URL 不一致")
    else:
        publication = await session.get(SeoContentPublication, relation_id)
        if publication is None or publication.tenant_id != tenant_id:
            raise _error(404, "relation_not_found", "发布记录不属于当前网站")
        content = await session.get(SeoContentAsset, publication.content_asset_id)
        if content is None or content.tenant_id != tenant_id or content.site_id != site_id:
            raise _error(404, "relation_not_found", "发布记录不属于当前网站")
        if not publication.page_url or canonical_url(publication.page_url) != canonical_url(url):
            raise _error(422, "relation_url_mismatch", "截图 URL 与发布页面 URL 不一致")
    return relation_type, relation_id


async def execute_page_capture(capture_id: int) -> None:
    """Use a fresh session after the response, following the SEO crawl-run pattern."""
    async with async_session_factory() as session:
        row = await session.get(SeoPageCapture, capture_id)
        if row is None or row.status != "pending":
            return
        site = await session.get(SeoSite, row.site_id)
        if (site is None or site.tenant_id != row.tenant_id
                or not domain_matches(row.source_url, f"https://{site.canonical_domain}")
                or not await seo_site_is_operational(session, row.tenant_id, row.site_id)):
            row.status, row.error_code = "failed", "site_inactive"
            await session.commit()
            return
        row.status = "running"
        row.captured_at = datetime.now(timezone.utc)
        await session.commit()
        arguments = dict(tenant_id=row.tenant_id, site_id=row.site_id,
                         relation_type=row.relation_type, relation_id=row.relation_id, url=row.source_url)
    try:
        result = await asyncio.wait_for(
            _capture_service().capture_page(**arguments),
            timeout=get_settings().seo_page_capture_timeout_seconds + 10,
        )
    except Exception:
        logger.exception("SEO page capture worker failed: capture_id=%s", capture_id)
        result = None
    async with async_session_factory() as session:
        row = await session.get(SeoPageCapture, capture_id)
        if row is None or row.status != "running":
            _discard_image(result)
            return
        if not await seo_site_is_operational(session, row.tenant_id, row.site_id):
            row.status, row.error_code = "failed", "site_inactive"
            _discard_image(result)
        elif result is None:
            row.status, row.error_code = "failed", "worker_error"
        else:
            for name in ("status", "error_code", "final_url", "http_status", "redirect_chain",
                         "warnings", "viewport_width", "viewport_height", "image_width", "image_height",
                         "sha256", "storage_key", "captured_at"):
                setattr(row, name, getattr(result, name))
        await session.commit()


@router.post("/site/page-captures", status_code=202)
async def create_page_capture(req: CaptureCreate, background_tasks: BackgroundTasks,
                              session: AsyncSession = Depends(get_session),
                              ctx: AuthContext = Depends(require_scoped_auth)) -> dict:
    ctx.ensure_tenant(req.tenant_id)
    if not ctx.can_edit("seo.site"):
        raise _error(403, "forbidden", "需要网站编辑权限")
    settings = get_settings()
    if not settings.seo_page_capture_enabled:
        raise _error(409, "capture_disabled", "页面截图功能未开启")
    # The site lock also serializes duplicate reservations across workers.
    site = await session.scalar(select(SeoSite).where(
        SeoSite.id == req.site_id, SeoSite.tenant_id == req.tenant_id,
    ).with_for_update().execution_options(populate_existing=True))
    if site is None or site.tenant_id != req.tenant_id:
        raise _error(404, "site_not_found", "SEO 网站不属于当前客户")
    if site.status != "active":
        raise _error(409, "site_inactive", "SEO 网站已暂停或归档")
    try:
        _check_url(req.url)
        valid_domain = domain_matches(req.url, f"https://{site.canonical_domain}")
    except (CaptureError, ValueError):
        valid_domain = False
    if not valid_domain:
        raise _error(422, "invalid_site_url", "URL 必须是当前网站域名下的 HTTP 或 HTTPS 地址")
    relation_type, relation_id = await _relation(
        session, req.tenant_id, req.site_id, req.url, req.relation_type, req.relation_id,
    )
    await _expire_stale(session, req.tenant_id, req.site_id)
    recent = await session.scalar(select(SeoPageCapture).where(
        SeoPageCapture.tenant_id == req.tenant_id, SeoPageCapture.site_id == req.site_id,
        SeoPageCapture.relation_type == relation_type, SeoPageCapture.relation_id == relation_id,
        SeoPageCapture.captured_at >= datetime.now(timezone.utc) - _COOLDOWN,
    ).order_by(SeoPageCapture.id.desc()).limit(1))
    if recent is not None:
        raise _error(409, "capture_recent", "该页面刚刚提交过截图请求")
    row = SeoPageCapture(tenant_id=req.tenant_id, site_id=req.site_id,
                         relation_type=relation_type, relation_id=relation_id,
                         source_url=req.url, status="pending", captured_at=datetime.now(timezone.utc),
                         redirect_chain=[], warnings={},
                         viewport_width=settings.seo_page_capture_viewport_width,
                         viewport_height=settings.seo_page_capture_viewport_height)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    background_tasks.add_task(execute_page_capture, row.id)
    return {"id": row.id, "status": row.status}


@router.get("/site/page-captures/{capture_id}")
async def get_page_capture(capture_id: PositiveInt, tenant_id: PositiveInt,
                           request: Request,
                           session: AsyncSession = Depends(get_session),
                           ctx: AuthContext = Depends(require_scoped_auth)) -> dict:
    ctx.ensure_tenant(tenant_id)
    return _payload(await _capture(session, tenant_id, capture_id,
                                   allow_stale_update=_primary_source(request)))


@router.get("/site/page-captures/{capture_id}/image")
async def get_page_capture_image(capture_id: PositiveInt, tenant_id: PositiveInt,
                                 request: Request,
                                 session: AsyncSession = Depends(get_session),
                                 ctx: AuthContext = Depends(require_scoped_auth)) -> Response:
    ctx.ensure_tenant(tenant_id)
    row = await _capture(session, tenant_id, capture_id,
                         allow_stale_update=_primary_source(request))
    if row.status != "succeeded" or not row.storage_key:
        raise _error(404, "image_not_ready", "截图图片尚不可用")
    try:
        path = capture_storage_path(get_settings().seo_page_capture_storage_dir, row.storage_key)
        data = Path(path).read_bytes()
    except (OSError, ValueError):
        raise _error(404, "image_not_found", "截图图片不可用") from None
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise _error(404, "image_not_found", "截图图片不可用")
    return Response(data, media_type="image/png", headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
    })


@router.get("/site/page-captures")
async def list_page_captures(tenant_id: PositiveInt, site_id: PositiveInt,
                             request: Request,
                             relation_type: Literal["site_page", "publication"] | None = None,
                             relation_id: PositiveInt | None = None,
                             page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                             session: AsyncSession = Depends(get_session),
                             ctx: AuthContext = Depends(require_scoped_auth)) -> dict:
    ctx.ensure_tenant(tenant_id)
    await _site(session, tenant_id, site_id)
    if (relation_type is None) != (relation_id is None):
        raise _error(422, "invalid_relation", "relation_type 和 relation_id 必须同时提供")
    if _primary_source(request):
        await _expire_stale(session, tenant_id, site_id)
        await session.commit()
    conditions = [SeoPageCapture.tenant_id == tenant_id, SeoPageCapture.site_id == site_id]
    if relation_type is not None:
        conditions.extend((SeoPageCapture.relation_type == relation_type,
                           SeoPageCapture.relation_id == relation_id))
    total = await session.scalar(select(func.count()).select_from(SeoPageCapture).where(*conditions))
    rows = list(await session.scalars(select(SeoPageCapture).where(*conditions)
        .order_by(SeoPageCapture.captured_at.desc(), SeoPageCapture.id.desc())
        .offset((page - 1) * page_size).limit(page_size)))
    return {"items": [_payload(row) for row in rows], "total": total or 0,
            "page": page, "page_size": page_size}
