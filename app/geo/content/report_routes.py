"""Scoped report, trend, citation and publication-import endpoints."""

from __future__ import annotations

from datetime import date, datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.geo.content.attribution import load_tenant_publications
from app.geo.content.publication_import import parse_rows, validate_rows, MAX_BYTES
from app.geo.content.report_data import SHANGHAI, citation_rows, trend_rows
from app.geo.content.time_windows import shanghai_day_bounds_utc_naive, shanghai_today
from app.geo.read_routes import read_session
from app.geo.tenant_scope import ensure_geo_entitlement, require_geo_read_entitlement
from app.geo.report_export import SECTION_DEFAULTS, build_report_html, build_xlsx, report_template
from app.geo.report_pdf import render_report_pdf
from app.models import GeoAnswerSnapshot, GeoArticleVersion, GeoChannelVariant, GeoPublication, GeoContentTask, GeoOptimizationBusiness, GeoOptimizationUnit, GeoPrompt, GeoProject, GeoTrackingEngine, Tenant
from app.security.auth import AuthContext, require_scoped_auth

router = APIRouter(tags=["GEO 报告"], dependencies=[Depends(require_scoped_auth)])


def _period(start: date | None, end: date | None) -> tuple[date, date]:
    end = end or shanghai_today()
    start = start or end.replace(day=1)
    if start > end or (end - start).days > 366:
        raise HTTPException(400, "观察期无效或超过 366 天")
    return start, end


async def _business(session, tenant_id, business_id):
    if business_id is None:
        return None
    row = await session.scalar(select(GeoOptimizationBusiness).where(
        GeoOptimizationBusiness.id == business_id, GeoOptimizationBusiness.tenant_id == tenant_id))
    if row is None:
        raise HTTPException(404, "项目不存在或不属于当前客户")
    return row


async def _project(session, tenant_id, project_id):
    if project_id is None:
        return None
    row = await session.scalar(select(GeoProject).where(GeoProject.id == project_id, GeoProject.tenant_id == tenant_id))
    if row is None:
        raise HTTPException(404, "GEO 项目不存在或不属于当前客户")
    return row


async def _evidence(session, tenant_id: int, business_id: int | None, start: date, end: date, project_id: int | None = None) -> dict:
    business = await _business(session, tenant_id, business_id)
    project, business_ids = None, [business_id] if business_id is not None else None
    if project_id is not None:
        from app.geo.project_scope import project_scope
        project, business_ids = await project_scope(session, tenant_id, project_id, business_id)
    tenant = await session.get(Tenant, tenant_id)
    stmt = select(GeoPrompt).where(GeoPrompt.tenant_id == tenant_id)
    if business_ids is not None:
        units = list(await session.scalars(select(GeoOptimizationUnit.id).where(
            GeoOptimizationUnit.tenant_id == tenant_id, GeoOptimizationUnit.business_id.in_(business_ids))))
        stmt = stmt.where(GeoPrompt.unit_id.in_(units))
    prompts = {p.id: p for p in await session.scalars(stmt)}
    if prompts:
        from_dt, _ = shanghai_day_bounds_utc_naive(start)
        _, to_dt = shanghai_day_bounds_utc_naive(end)
        snaps = list(await session.scalars(select(GeoAnswerSnapshot).where(
            GeoAnswerSnapshot.tenant_id == tenant_id, GeoAnswerSnapshot.prompt_id.in_(prompts),
            GeoAnswerSnapshot.captured_at >= from_dt, GeoAnswerSnapshot.captured_at < to_dt).order_by(GeoAnswerSnapshot.captured_at)))
    else:
        snaps = []
    pubs = await load_tenant_publications(session, tenant_id)
    if business_ids is not None:
        ids = set(await session.scalars(select(GeoContentTask.id).where(
            GeoContentTask.tenant_id == tenant_id, GeoContentTask.prompt_id.in_(prompts),
            (GeoContentTask.business_id.in_(business_ids) | GeoContentTask.business_id.is_(None)))))
        pubs = [p for p in pubs if p.task_id in ids]
    engines = list(await session.scalars(select(GeoTrackingEngine.engine_key).where(
        GeoTrackingEngine.tenant_id == tenant_id, GeoTrackingEngine.enabled.is_(True))))
    checks = {}
    if pubs:
        from app.geo.publication_monitor import report_check
        pairs = (await session.execute(select(GeoPublication, GeoChannelVariant).join(
            GeoChannelVariant, GeoChannelVariant.id == GeoPublication.variant_id).join(
            GeoContentTask, GeoContentTask.id == GeoChannelVariant.task_id).where(
            GeoContentTask.tenant_id == tenant_id, GeoPublication.id.in_([p.id for p in pubs])))).all()
        task_ids = {variant.task_id for _, variant in pairs}
        latest_versions = select(GeoArticleVersion.task_id, func.max(GeoArticleVersion.version_no).label('version_no')).where(
            GeoArticleVersion.task_id.in_(task_ids)).group_by(GeoArticleVersion.task_id).subquery()
        latest = dict((await session.execute(select(GeoArticleVersion.task_id, GeoArticleVersion.id).join(
            latest_versions, (latest_versions.c.task_id == GeoArticleVersion.task_id) &
            (latest_versions.c.version_no == GeoArticleVersion.version_no)))).all())
        checks = {pub.id: report_check(variant, pub, latest.get(variant.task_id)) for pub, variant in pairs}
    return {"client_name": tenant.name if tenant else f"客户 {tenant_id}",
            "project_name": project.name if project else business.name if business else "全部业务", "start": start, "end": end,
            "data_scope": {"kind": "project" if project else "business" if business else "tenant",
                           "project_id": project_id, "business_ids": business_ids},
            "prompts": prompts, "snapshots": snaps, "publications": pubs, "publication_checks": checks,
            "engines": sorted(set(engines) | {s.engine for s in snaps})}


@router.get("/reports/mention-trends", dependencies=[Depends(require_geo_read_entitlement)])
async def mention_trends(tenant_id: int, business_id: int | None = None, from_: date | None = Query(None, alias="from"),
                         to: date | None = None, granularity: str = "day", provenance: str = "real", project_id: int | None = None,
                         ctx: AuthContext = Depends(require_scoped_auth), session: AsyncSession = Depends(read_session)):
    ctx.ensure_tenant(tenant_id)
    start, end = _period(from_, to)
    if granularity not in {"day", "week", "month"} or provenance not in {"real", "manual", "simulated", "unknown"}:
        raise HTTPException(400, "粒度或样本来源无效")
    data = await _evidence(session, tenant_id, business_id, start, end, project_id)
    return {"items": trend_rows(data["snapshots"], data["prompts"], start, end, granularity, provenance, data["engines"]),
            "data_scope": data["data_scope"], "granularity": granularity, "provenance": provenance, "timezone": "Asia/Shanghai"}


@router.get("/reports/url-citations", dependencies=[Depends(require_geo_read_entitlement)])
async def url_citations(tenant_id: int, business_id: int | None = None, from_: date | None = Query(None, alias="from"),
                        to: date | None = None, provenance: str = "real", project_id: int | None = None, ctx: AuthContext = Depends(require_scoped_auth),
                        session: AsyncSession = Depends(read_session)):
    ctx.ensure_tenant(tenant_id)
    start, end = _period(from_, to)
    if provenance not in {"real", "manual", "simulated", "unknown"}:
        raise HTTPException(400, "样本来源无效")
    data = await _evidence(session, tenant_id, business_id, start, end, project_id)
    return {"items": citation_rows(data["publications"], data["snapshots"], start, end, provenance, data["publication_checks"]),
            "data_scope": data["data_scope"], "provenance": provenance, "timezone": "Asia/Shanghai"}


class ImportConfirm(BaseModel):
    tenant_id: int
    business_id: int | None = None
    project_id: int | None = None
    rows: list[dict] = Field(max_length=500)


async def _tasks_pubs(session, tenant_id, project_id=None, business_id=None):
    tasks = list(await session.scalars(select(GeoContentTask).where(GeoContentTask.tenant_id == tenant_id)))
    pubs = await load_tenant_publications(session, tenant_id)
    questions = {p.id: p.question for p in await session.scalars(select(GeoPrompt).where(GeoPrompt.tenant_id == tenant_id))}
    if project_id is not None:
        from app.geo.project_scope import project_scope, prompt_ids_for_businesses
        _, ids = await project_scope(session, tenant_id, project_id, business_id)
        prompt_ids = set(await prompt_ids_for_businesses(session, tenant_id, ids))
        tasks = [t for t in tasks if t.prompt_id in prompt_ids and (t.business_id is None or t.business_id in ids)]
        task_ids = {t.id for t in tasks}
        pubs = [p for p in pubs if p.task_id in task_ids]
        questions = {key: value for key, value in questions.items() if key in prompt_ids}
    return tasks, pubs, questions


@router.post("/reports/publication-links/preview")
async def preview_publication_links(tenant_id: int = Query(...), business_id: int | None = Query(None),
                                    project_id: int | None = Query(None),
                                    file: UploadFile | None = File(None), pasted: str = Form(""),
                                    ctx: AuthContext = Depends(require_scoped_auth), session: AsyncSession = Depends(get_session)):
    ctx.ensure_tenant(tenant_id)
    await ensure_geo_entitlement(session, tenant_id)
    await _business(session, tenant_id, business_id)
    if file and file.filename and not file.filename.lower().endswith((".csv", ".xlsx", ".tsv")):
        raise HTTPException(400, "仅支持 CSV、XLSX 或制表符文本")
    content = await file.read(MAX_BYTES + 1) if file else None
    try:
        rows = parse_rows(filename=file.filename if file else "", content=content, pasted=pasted)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    tasks, pubs, questions = await _tasks_pubs(session, tenant_id, project_id, business_id)
    items = validate_rows(rows, tasks, pubs, business_id, questions)
    return {"items": items, "valid_count": sum(r["status"] == "有效" for r in items), "total": len(items)}


@router.post("/reports/publication-links/confirm")
async def confirm_publication_links(req: ImportConfirm, ctx: AuthContext = Depends(require_scoped_auth),
                                    session: AsyncSession = Depends(get_session)):
    from app.geo.content.routes import _get_task, _variants, _write_publication, _ensure_default_publishing_channels
    from app.geo.content.channel_registry import publication_publish_mode, publish_mode_for_channel, registry_row_dicts
    from app.geo.content.gate import PublishGateError

    ctx.ensure_tenant(req.tenant_id)
    await ensure_geo_entitlement(session, req.tenant_id)
    await _business(session, req.tenant_id, req.business_id)
    tasks, pubs, questions = await _tasks_pubs(session, req.tenant_id, req.project_id, req.business_id)
    items = validate_rows(req.rows, tasks, pubs, req.business_id, questions)
    registry = registry_row_dicts(await _ensure_default_publishing_channels(session, req.tenant_id))
    applied = 0
    for item in items:
        if item["status"] != "有效":
            continue
        try:
            if req.project_id is not None:
                # Binding changes take the same tenant lock. Recheck after every
                # per-row commit; a preview is never authority to write later.
                await session.scalar(select(Tenant.id).where(Tenant.id == req.tenant_id).with_for_update())
                from app.geo.project_scope import project_scope, prompt_ids_for_businesses
                _, current_ids = await project_scope(session, req.tenant_id, req.project_id, req.business_id)
                current_prompts = await prompt_ids_for_businesses(session, req.tenant_id, current_ids)
            task = await _get_task(session, int(item["task_id"]), req.tenant_id)
            if req.project_id is not None and (task.prompt_id not in current_prompts or
                    (task.business_id is not None and task.business_id not in current_ids)):
                raise HTTPException(404, "内容任务已移出当前项目，请重新预览")
            variant = next((v for v in await _variants(session, task.id) if v.channel == item["channel"]), None)
            if variant is None:
                raise ValueError("请先生成该渠道版本")
            when = datetime.fromisoformat(item["published_at"]) if item["published_at"] else None
            if when:
                when = (when.replace(tzinfo=SHANGHAI) if when.tzinfo is None else when).astimezone(timezone.utc).replace(tzinfo=None)
            created = await _write_publication(session, task=task, variant=variant, channel=item["channel"],
                                     published_url=item["url"], note="批量导入发布链接",
                                     publish_mode=publication_publish_mode(publish_mode_for_channel(item["channel"], registry)),
                                     published_at=when)
            await session.commit()
            if created is False:
                item["status"] = "错误"
                item["errors"] = ["发布链接已存在"]
            else:
                item["status"] = "已导入"
                applied += 1
        except (HTTPException, PublishGateError, ValueError) as exc:
            await session.rollback()
            item["status"] = "错误"
            item["errors"] = [str(getattr(exc, "detail", exc))]
    return {"items": items, "applied_count": applied, "total": len(items)}


@router.get("/reports/template", dependencies=[Depends(require_geo_read_entitlement)])
async def get_report_template(tenant_id: int, project_id: int, ctx: AuthContext = Depends(require_scoped_auth),
                              session: AsyncSession = Depends(read_session)):
    ctx.ensure_tenant(tenant_id)
    project = await _project(session, tenant_id, project_id)
    return {"sections": report_template(project.project_settings)}


class TemplateUpdate(BaseModel):
    tenant_id: int
    project_id: int
    sections: list[dict] | None = None


@router.put("/reports/template")
async def put_report_template(req: TemplateUpdate, ctx: AuthContext = Depends(require_scoped_auth),
                              session: AsyncSession = Depends(get_session)):
    ctx.ensure_tenant(req.tenant_id)
    await ensure_geo_entitlement(session, req.tenant_id)
    project = await session.scalar(select(GeoProject).where(GeoProject.id == req.project_id,
        GeoProject.tenant_id == req.tenant_id).with_for_update())
    if project is None:
        raise HTTPException(404, "GEO 项目不存在")
    if req.sections is not None:
        if not all(isinstance(s, dict) for s in req.sections):
            raise HTTPException(400, "报告章节无效")
        keys = [s.get("key") for s in req.sections]
        if len(keys) != len(SECTION_DEFAULTS) or set(keys) != {s["key"] for s in SECTION_DEFAULTS} or any(len(str(s.get("title") or "")) > 60 for s in req.sections):
            raise HTTPException(400, "报告章节无效")
    profile = dict(project.project_settings or {})
    if req.sections is None:
        profile.pop("geo_report_template", None)
    else:
        profile["geo_report_template"] = report_template({"geo_report_template": req.sections})
    project.project_settings = profile
    await session.commit()
    return {"sections": report_template(profile)}


def _download(content: bytes, filename: str, media_type: str):
    encoded = quote(filename)
    return Response(content, media_type=media_type,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}", "Cache-Control": "private, no-store"})


@router.get("/reports/export.xlsx", dependencies=[Depends(require_geo_read_entitlement)])
async def export_geo_xlsx(tenant_id: int, business_id: int | None = None, project_id: int | None = None, from_: date | None = Query(None, alias="from"),
                          to: date | None = None, ctx: AuthContext = Depends(require_scoped_auth), session: AsyncSession = Depends(read_session)):
    ctx.ensure_tenant(tenant_id)
    start, end = _period(from_, to)
    data = await _evidence(session, tenant_id, business_id, start, end, project_id)
    project = await _project(session, tenant_id, project_id)
    if project:
        data["project_name"] = project.name
    try:
        xlsx = build_xlsx(data)
    except ValueError as exc:
        raise HTTPException(413, str(exc)) from exc
    return _download(xlsx, f"GEO-明细-{start}-{end}.xlsx",
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/reports/export.pdf", dependencies=[Depends(require_geo_read_entitlement)])
async def export_geo_pdf(tenant_id: int, business_id: int | None = None, project_id: int | None = None, from_: date | None = Query(None, alias="from"),
                         to: date | None = None, ctx: AuthContext = Depends(require_scoped_auth), session: AsyncSession = Depends(read_session)):
    ctx.ensure_tenant(tenant_id)
    start, end = _period(from_, to)
    data = await _evidence(session, tenant_id, business_id, start, end, project_id)
    project = await _project(session, tenant_id, project_id)
    if project:
        data["project_name"] = project.name
    html = build_report_html(data, template=report_template(project.project_settings if project else None))
    pdf = await render_report_pdf(html)
    return _download(pdf, f"GEO-报告-{start}-{end}.pdf", "application/pdf")
