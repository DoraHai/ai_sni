"""Site scoped TDK review draft template and file export."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from pydantic import BaseModel, PositiveInt
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.seo_page_captures import CaptureCreate, create_page_capture
from app.api.seo_site_analytics import error, scope
from app.config import get_settings
from app.models.seo import SeoInternalLink, SeoKeywordAsset, SeoSitePage
from app.models.seo_page_capture import SeoPageCapture
from app.models.seo_tdk_review import SeoSiteTdkReviewTemplate, SeoTdkReviewBatch
from app.security.auth import AuthContext
from app.seo_demo_source import get_seo_session as get_session, require_seo_scoped_auth as require_scoped_auth
from app.seo_monthly_report import render_report_pdf
from app.seo_page_capture import capture_storage_path
from app.seo_tdk_review import (DEFAULT_TDK_REVIEW_COLUMNS, DEFAULT_TDK_REVIEW_SECTIONS,
    build_tdk_review_context, render_tdk_review_docx, render_tdk_review_html,
    validate_tdk_review_template)

router = APIRouter()
_playwright_factory = None


class TdkReviewTemplateUpdate(BaseModel):
    tenant_id: PositiveInt
    site_id: PositiveInt
    sections: list[dict]
    columns: dict


class TdkReviewExport(BaseModel):
    tenant_id: PositiveInt
    site_id: PositiveInt
    page_ids: list[PositiveInt]
    format: Literal["docx", "pdf"]
    trigger_capture: bool = False


def _template_payload(row, tenant_id):
    current = row if row and row.tenant_id == tenant_id else None
    return {"sections": current.sections if current else list(DEFAULT_TDK_REVIEW_SECTIONS),
            "columns": current.columns if current else DEFAULT_TDK_REVIEW_COLUMNS.copy(),
            "is_default": current is None}


@router.get("/site/tdk-review/template")
async def get_tdk_review_template(tenant_id: PositiveInt, site_id: PositiveInt,
                                  session: AsyncSession = Depends(get_session),
                                  ctx: AuthContext = Depends(require_scoped_auth)):
    await scope(session, ctx, tenant_id, site_id)
    return _template_payload(await session.get(SeoSiteTdkReviewTemplate, site_id), tenant_id)


@router.put("/site/tdk-review/template")
async def put_tdk_review_template(req: TdkReviewTemplateUpdate,
                                  session: AsyncSession = Depends(get_session),
                                  ctx: AuthContext = Depends(require_scoped_auth)):
    await scope(session, ctx, req.tenant_id, req.site_id, True)
    try:
        template = validate_tdk_review_template(req.sections, req.columns)
    except ValueError as exc:
        raise error(422, "invalid_template", str(exc)) from exc
    row = await session.get(SeoSiteTdkReviewTemplate, req.site_id)
    if row is None:
        row = SeoSiteTdkReviewTemplate(site_id=req.site_id, tenant_id=req.tenant_id)
        session.add(row)
    row.sections, row.columns, row.updated_by = template["sections"], template["columns"], ctx.user_id
    await session.commit()
    return {**template, "is_default": False}


@router.delete("/site/tdk-review/template")
async def delete_tdk_review_template(tenant_id: PositiveInt, site_id: PositiveInt,
                                     session: AsyncSession = Depends(get_session),
                                     ctx: AuthContext = Depends(require_scoped_auth)):
    await scope(session, ctx, tenant_id, site_id, True)
    row = await session.get(SeoSiteTdkReviewTemplate, site_id)
    if row and row.tenant_id == tenant_id:
        await session.delete(row)
        await session.commit()
    return _template_payload(None, tenant_id)


@router.post("/site/tdk-review/export")
async def export_tdk_review(req: TdkReviewExport, background_tasks: BackgroundTasks,
                            session: AsyncSession = Depends(get_session),
                            ctx: AuthContext = Depends(require_scoped_auth)) -> Response:
    site = await scope(session, ctx, req.tenant_id, req.site_id)
    if req.trigger_capture and not ctx.can_edit("seo.site"):
        raise error(403, "forbidden", "提交截图任务需要网站编辑权限")
    ids = list(dict.fromkeys(req.page_ids))
    if not 1 <= len(ids) <= 50:
        raise error(422, "invalid_page_count", "请选择 1 至 50 个页面")
    pages = (await session.scalars(select(SeoSitePage).where(
        SeoSitePage.tenant_id == req.tenant_id, SeoSitePage.site_id == req.site_id,
        SeoSitePage.id.in_(ids)))).all()
    if len(pages) != len(ids):
        raise error(404, "page_not_found", "部分页面不属于当前网站或客户")
    by_id = {page.id: page for page in pages}
    pages = [by_id[key] for key in ids]
    batch = SeoTdkReviewBatch(tenant_id=req.tenant_id, site_id=req.site_id, page_ids=ids,
                              created_by=ctx.user_id, format=req.format, status="running")
    session.add(batch)
    await session.flush()
    await session.commit()

    try:
        keyword_ids = {page.target_keyword_id for page in pages if page.target_keyword_id}
        keywords = (await session.scalars(select(SeoKeywordAsset).where(
            SeoKeywordAsset.tenant_id == req.tenant_id, SeoKeywordAsset.site_id == req.site_id,
            or_(SeoKeywordAsset.id.in_(keyword_ids), SeoKeywordAsset.landing_page.in_([page.url for page in pages]))))).all()
        edges = (await session.scalars(select(SeoInternalLink).where(
            SeoInternalLink.tenant_id == req.tenant_id, SeoInternalLink.site_id == req.site_id,
            or_(SeoInternalLink.source_page_id.in_(ids), SeoInternalLink.target_page_id.in_(ids))))).all()
        related_ids = {key for edge in edges for key in (edge.source_page_id, edge.target_page_id)} - set(ids)
        if related_ids:
            related = (await session.scalars(select(SeoSitePage).where(
                SeoSitePage.tenant_id == req.tenant_id, SeoSitePage.site_id == req.site_id,
                SeoSitePage.id.in_(related_ids)))).all()
        else:
            related = []
        captures = (await session.scalars(select(SeoPageCapture).where(
            SeoPageCapture.tenant_id == req.tenant_id, SeoPageCapture.site_id == req.site_id,
            SeoPageCapture.relation_type == "site_page", SeoPageCapture.relation_id.in_(ids),
            SeoPageCapture.status == "succeeded"))).all()
        settings = get_settings()
        notes, images = {}, {}
        for capture in captures:
            if capture.storage_key and capture.storage_key not in images:
                try:
                    images[capture.storage_key] = capture_storage_path(settings.seo_page_capture_storage_dir, capture.storage_key).read_bytes()
                except (OSError, ValueError):
                    pass
        captured_ids = {row.relation_id for row in captures if row.storage_key in images}
        for page in pages:
            if page.id in captured_ids:
                continue
            if not settings.seo_page_capture_enabled:
                notes[page.id] = "暂无截图；截图服务未启用"
            elif req.trigger_capture:
                try:
                    await create_page_capture(CaptureCreate(tenant_id=req.tenant_id, site_id=req.site_id,
                        relation_type="site_page", relation_id=page.id), background_tasks, session, ctx)
                    notes[page.id] = "暂无截图；已提交截图任务，请稍后重新导出"
                except HTTPException as exc:
                    notes[page.id] = "暂无截图；截图任务未提交：" + str(exc.detail.get("message", "请稍后重试"))
            else:
                notes[page.id] = "暂无截图"
        template_row = await session.get(SeoSiteTdkReviewTemplate, req.site_id)
        template = _template_payload(template_row, req.tenant_id)
        context = build_tdk_review_context(site_name=site.name, pages=pages + related,
            batch_id=batch.id, generated_at=datetime.now(timezone.utc), keywords=keywords,
            links=edges, captures=captures, images=images, capture_notes=notes)
        context["pages"] = context["pages"][:len(pages)]
        if req.format == "docx":
            content = render_tdk_review_docx(context, template)
            mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            content = await render_report_pdf(render_tdk_review_html(context, template), settings,
                                              playwright_factory=_playwright_factory)
            mime = "application/pdf"
        batch.status = "succeeded"
        await session.commit()
    except Exception as exc:
        batch.status, batch.error = "failed", str(exc)[:1000]
        await session.commit()
        if req.format == "pdf":
            raise error(503, "browser_unavailable", "审核稿 PDF 生成失败：服务器浏览器不可用或生成超时") from exc
        raise
    safe_site = re.sub(r'[\x00-\x1f\x7f\\/:*?"<>|]+', "_", site.name).strip(" .") or "站点"
    day = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).strftime("%Y%m%d")
    filename = f"TDK审核稿-{safe_site}-{day}.{req.format}"
    return Response(content, media_type=mime, headers={
        "Content-Disposition": f"attachment; filename=tdk-review-{day}.{req.format}; filename*=UTF-8''{quote(filename)}",
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        "X-TDK-Review-Batch-ID": str(batch.id)})
