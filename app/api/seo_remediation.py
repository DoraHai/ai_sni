"""Explicit user-triggered AI preview; persistence uses the existing content workflow."""

import asyncio
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, PositiveInt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.deepseek import is_enabled
from app.api.seo_site_diagnostics import _scope
from app.database import get_session
from app.models.module_workspace import SeoSite
from app.models.seo import SeoSitePage
from app.security.auth import AuthContext, require_scoped_auth
from app.seo_site_diagnostics import diagnostic_payload
from app import seo_remediation as service

router = APIRouter()


class RemediationRequest(BaseModel):
    tenant_id: PositiveInt
    site_id: PositiveInt
    page_id: PositiveInt


@router.post("/site-pages/ai-remediation")
async def preview_remediation(
    req: RemediationRequest, ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
):
    await _scope(session, ctx, req.tenant_id, req.site_id, write=True)
    if ctx.user_id is None or not ctx.can_edit("seo.content"):
        raise HTTPException(403, "需要已登录用户及内容编辑权限")
    row = await session.scalar(select(SeoSitePage).where(
        SeoSitePage.tenant_id == req.tenant_id, SeoSitePage.site_id == req.site_id, SeoSitePage.id == req.page_id,
    ))
    if row is None:
        raise HTTPException(404, "页面不存在")
    site = await session.scalar(select(SeoSite).where(SeoSite.id == req.site_id, SeoSite.tenant_id == req.tenant_id))
    if not is_enabled():
        raise HTTPException(503, "AI 提供方未配置，请使用规则建议或人工整改")
    url, domain, diagnostic = row.url, site.canonical_domain, diagnostic_payload(row)
    reservation = await service.reserve(session, req.tenant_id)
    success = False
    try:
        async with asyncio.timeout(80):
            evidence = await service.read_evidence(url, domain)
            proposal = await service.generate(evidence, diagnostic)
        success = True
        return {"source": "ai", "status": "preview", "saved": False, "page_id": req.page_id,
                "site_id": req.site_id, "tenant_id": req.tenant_id, "proposal": proposal,
                "evidence": evidence, "stored_diagnostic": diagnostic, "daily_limit": service.DAILY_LIMIT,
                "note": "AI 草稿需人工核实；引用证据不保证推理正确。尚未保存，不修改当前 TDK、索引设置或官网。"}
    except TimeoutError as exc:
        raise HTTPException(504, "整改请求超时，本次不扣整改额度；请稍后重试") from exc
    finally:
        await service.settle(session, req.tenant_id, reservation, success=success)
