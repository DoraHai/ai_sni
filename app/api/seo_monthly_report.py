"""Site scoped PDF monthly reports and section settings."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, PositiveInt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.seo_site_analytics import error, scope
from app.config import get_settings
from app.models.seo import SeoContentAsset, SeoContentPublication, SeoKeywordAsset
from app.models.seo_page_capture import SeoPageCapture
from app.models.seo_site_analytics import SeoSiteAnalyticsMonthly, SeoSiteAnalyticsSource, SeoSiteExportTemplate
from app.models.seo_monthly_report import SeoSiteReportTemplate
from app.models.tenant import Tenant
from app.security.auth import AuthContext
from app.seo_demo_source import get_seo_session as get_session, require_seo_scoped_auth as require_scoped_auth
from app.seo_monthly_report import (DEFAULT_REPORT_SECTIONS, MAX_APPENDIX_IMAGES,
    build_report_context, render_report_html, render_report_pdf, validate_report_sections)
from app.seo_page_capture import capture_storage_path
from app.seo_publication_export import capture_fields, month_bounds
from app.seo_site_analytics import AnalyticsError, validate_month

router = APIRouter()
_playwright_factory = None  # Test injection; production uses the installed Playwright runtime.


class ReportTemplateUpdate(BaseModel):
    tenant_id: PositiveInt
    site_id: PositiveInt
    sections: list[dict]


@router.get("/site/reports/monthly-template")
async def get_report_template(tenant_id: PositiveInt, site_id: PositiveInt,
                              session: AsyncSession = Depends(get_session),
                              ctx: AuthContext = Depends(require_scoped_auth)):
    await scope(session, ctx, tenant_id, site_id)
    row = await session.get(SeoSiteReportTemplate, site_id)
    return {"sections": row.sections if row and row.tenant_id == tenant_id else list(DEFAULT_REPORT_SECTIONS),
            "is_default": row is None or row.tenant_id != tenant_id}


@router.put("/site/reports/monthly-template")
async def put_report_template(req: ReportTemplateUpdate, session: AsyncSession = Depends(get_session),
                              ctx: AuthContext = Depends(require_scoped_auth)):
    await scope(session, ctx, req.tenant_id, req.site_id, True)
    try:
        sections = validate_report_sections(req.sections)
    except ValueError as exc:
        raise error(422, "invalid_template", str(exc)) from exc
    row = await session.get(SeoSiteReportTemplate, req.site_id)
    if row is None:
        row = SeoSiteReportTemplate(site_id=req.site_id, tenant_id=req.tenant_id)
        session.add(row)
    row.sections, row.updated_by = sections, ctx.user_id
    await session.commit()
    return {"sections": sections, "is_default": False}


@router.delete("/site/reports/monthly-template")
async def delete_report_template(tenant_id: PositiveInt, site_id: PositiveInt,
                                 session: AsyncSession = Depends(get_session),
                                 ctx: AuthContext = Depends(require_scoped_auth)):
    await scope(session, ctx, tenant_id, site_id, True)
    row = await session.get(SeoSiteReportTemplate, site_id)
    if row and row.tenant_id == tenant_id:
        await session.delete(row)
        await session.commit()
    return {"sections": list(DEFAULT_REPORT_SECTIONS), "is_default": True}


@router.get("/site/reports/monthly")
async def get_monthly_report(tenant_id: PositiveInt, site_id: PositiveInt, month: str,
                             session: AsyncSession = Depends(get_session),
                             ctx: AuthContext = Depends(require_scoped_auth)) -> Response:
    site = await scope(session, ctx, tenant_id, site_id)
    try:
        validate_month(month)
        start, end = month_bounds(month)
    except (AnalyticsError, ValueError, OverflowError) as exc:
        raise error(422, getattr(exc, "code", "invalid_month"), str(exc)) from exc
    pairs = (await session.execute(select(SeoContentPublication, SeoContentAsset).join(
        SeoContentAsset, SeoContentPublication.content_asset_id == SeoContentAsset.id).where(
        SeoContentPublication.tenant_id == tenant_id, SeoContentAsset.tenant_id == tenant_id,
        SeoContentAsset.site_id == site_id, SeoContentPublication.status == "published",
        SeoContentPublication.published_at >= start, SeoContentPublication.published_at < end,
    ).order_by(SeoContentPublication.published_at, SeoContentPublication.id))).all()
    ids = [publication.id for publication, _ in pairs]
    captures = defaultdict(list)
    if ids:
        evidence = (await session.scalars(select(SeoPageCapture).where(
            SeoPageCapture.tenant_id == tenant_id, SeoPageCapture.site_id == site_id,
            SeoPageCapture.relation_type == "publication", SeoPageCapture.relation_id.in_(ids)))).all()
        for item in evidence:
            captures[item.relation_id].append(item)
    keyword_ids = {key for _, asset in pairs for key in
                   (asset.keyword_ids or ([asset.keyword_id] if asset.keyword_id else [])) if isinstance(key, int)}
    keywords = {}
    if keyword_ids:
        found = (await session.scalars(select(SeoKeywordAsset).where(
            SeoKeywordAsset.tenant_id == tenant_id, SeoKeywordAsset.site_id == site_id,
            SeoKeywordAsset.id.in_(keyword_ids)))).all()
        keywords = {item.id: item.keyword for item in found}
    rows = []
    for publication, asset in pairs:
        chosen = capture_fields(captures[publication.id])
        selected = asset.keyword_ids or ([asset.keyword_id] if asset.keyword_id else [])
        rows.append({"platform": publication.platform_name, "title": asset.title,
                     "keywords": "、".join(keywords[key] for key in selected if key in keywords),
                     "page_url": publication.page_url, "published_at": publication.published_at,
                     "capture_status": chosen["capture_status"], "image_key": chosen["image_key"],
                     "captured_at": chosen["captured_at"], "notes": chosen["capture_note"],
                     "capture_kind": chosen["capture_kind"]})
    settings = get_settings()
    images = {}
    for row in rows:
        key = row.get("image_key")
        if key and key not in images and len(images) < MAX_APPENDIX_IMAGES:
            try:
                images[key] = capture_storage_path(settings.seo_page_capture_storage_dir, key).read_bytes()
            except (OSError, ValueError):
                row["capture_status"] = "失败：截图图片不可用"
    monthly = (await session.scalars(select(SeoSiteAnalyticsMonthly).where(
        SeoSiteAnalyticsMonthly.tenant_id == tenant_id, SeoSiteAnalyticsMonthly.site_id == site_id,
        SeoSiteAnalyticsMonthly.month == month))).all()
    sources = (await session.scalars(select(SeoSiteAnalyticsSource).where(
        SeoSiteAnalyticsSource.tenant_id == tenant_id, SeoSiteAnalyticsSource.site_id == site_id))).all()
    export = await session.get(SeoSiteExportTemplate, site_id)
    template = await session.get(SeoSiteReportTemplate, site_id)
    tenant = await session.get(Tenant, tenant_id)
    context = build_report_context(site_name=site.name, tenant_name=tenant.name if tenant else None,
        month=month, rows=rows, monthly_rows=monthly, sources=sources,
        columns=export.columns if export and export.tenant_id == tenant_id else None, images=images,
        generated_at=datetime.now(timezone.utc))
    html = render_report_html(context, template.sections if template and template.tenant_id == tenant_id else None)
    try:
        pdf = await render_report_pdf(html, settings, playwright_factory=_playwright_factory)
    except (asyncio.TimeoutError, TimeoutError) as exc:
        raise error(503, "report_timeout", "月报生成失败：生成超时，请稍后重试") from exc
    except (ImportError, FileNotFoundError) as exc:
        raise error(503, "browser_unavailable", "月报生成失败：服务器未安装浏览器运行环境") from exc
    except Exception as exc:
        if "timeout" in type(exc).__name__.lower() or "timeout" in str(exc).lower():
            raise error(503, "report_timeout", "月报生成失败：生成超时，请稍后重试") from exc
        if "executable" in str(exc).lower() or "browser" in str(exc).lower():
            raise error(503, "browser_unavailable", "月报生成失败：服务器未安装浏览器运行环境") from exc
        raise
    safe_site = re.sub(r'[\\/:*?"<>|\r\n]+', "_", site.name).strip(" .") or "站点"
    filename = f"SEO月报-{safe_site}-{month}.pdf"
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename=seo-report-{month}.pdf; filename*=UTF-8''{quote(filename)}",
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
