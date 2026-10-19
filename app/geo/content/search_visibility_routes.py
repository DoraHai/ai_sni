from app.security.advisor_operation_call import checked_call
"""Project-scoped search visibility API, mounted only under existing GEO routes."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session
from app.geo.content.search_visibility import (
    KIND, NOTICE, StopRun, VisibilityConfig, access_state, create_run, csv_text,
    execute_run, is_admin, is_advisor, month_usage, resolve_config, run_payload, week_start,
)
from app.models import GeoAsyncJob, GeoOptimizationUnit, GeoProject, Tenant
from app.module_scope import ensure_module_access
from app.security.auth import AuthContext, require_scoped_auth
from app.security.geo_operation_audit import audit_geo_operation

router = APIRouter(tags=["GEO 搜索可见度"])


async def load_project(session, ctx, tenant_id, project_id):
    await ensure_module_access(session, ctx, tenant_id, "geo")
    project = await session.get(GeoProject, project_id)
    if project is None or project.tenant_id != tenant_id:
        raise HTTPException(404, "GEO 项目不存在")
    if getattr(ctx, "advisor_scope", None) is not None:
        from app.security.advisor_write_reads import assigned_scope
        from app.security.advisor_scope import deny
        owned, _ = await assigned_scope(session, ctx)
        if project_id not in owned:
            deny(403, "ADVISOR_ASSIGNMENT_REQUIRED", "需要这个项目的有效顾问分配")
    tenant = await session.get(Tenant, tenant_id)
    return project, resolve_config(project, tenant)


def require_advisor(ctx):
    if not is_advisor(ctx):
        raise HTTPException(403, "仅 GEO 顾问或超管可设置和运行")


@router.get("/projects/{project_id}/search-visibility/config")
async def get_config(project_id: int, tenant_id: int = Query(...),
                     ctx: AuthContext = Depends(require_scoped_auth),
                     session: AsyncSession = Depends(get_session)):
    require_advisor(ctx)
    project, config = await load_project(session, ctx, tenant_id, project_id)
    query = select(GeoOptimizationUnit.keyword).where(
        GeoOptimizationUnit.tenant_id == tenant_id, GeoOptimizationUnit.status == "active",
        GeoOptimizationUnit.keyword.is_not(None),
    ).order_by(GeoOptimizationUnit.sort_order, GeoOptimizationUnit.id).limit(100)
    from app.security.advisor_write_reads import filter_query
    query = await filter_query(session, ctx, query, GeoOptimizationUnit)
    keywords = await session.scalars(query)
    suggested = list(dict.fromkeys(k.strip() for k in keywords if k and 0 < len(k.strip()) <= 128))[:20]
    return {**access_state(config, ctx), "config": config.model_dump(), "notice": NOTICE,
            "suggested_core_terms": suggested, "suggested_core_terms_scope": "assigned_projects" if getattr(ctx, "advisor_scope", None) is not None else "tenant"}


@router.put("/projects/{project_id}/search-visibility/config")
@audit_geo_operation('PUT', '/api/v1/geo/projects/{project_id}/search-visibility/config')
@checked_call
async def put_config(project_id: int, req: VisibilityConfig, tenant_id: int = Query(...),
                     ctx: AuthContext = Depends(require_scoped_auth),
                     session: AsyncSession = Depends(get_session)):
    require_advisor(ctx)
    project, _ = await load_project(session, ctx, tenant_id, project_id)
    # Serialize with task admission and preserve unrelated project settings.
    project = await session.scalar(select(GeoProject).where(GeoProject.id == project.id).with_for_update().execution_options(populate_existing=True))
    values = req.model_dump()
    if getattr(ctx, 'advisor_scope', None) is not None:
        current = (project.project_settings or {}).get('deepseek_visibility') or {}
        values = VisibilityConfig.model_validate({**current, **req.model_dump(exclude_unset=True)}).model_dump()
    project.project_settings = {**(project.project_settings or {}), "deepseek_visibility": values}
    await session.commit()
    return {**access_state(VisibilityConfig.model_validate(values), ctx), "config": values, "notice": NOTICE}


@router.post("/projects/{project_id}/search-visibility/run", status_code=202)
@audit_geo_operation('POST', '/api/v1/geo/projects/{project_id}/search-visibility/run', success_status=202)
@checked_call
async def run_now(project_id: int, background: BackgroundTasks, tenant_id: int = Query(...),
                  ctx: AuthContext = Depends(require_scoped_auth),
                  session: AsyncSession = Depends(get_session)):
    require_advisor(ctx)
    project, config = await load_project(session, ctx, tenant_id, project_id)
    state = access_state(config, ctx)
    if state["state"] != "ready":
        return state
    if project.status != "active":
        raise HTTPException(409, "项目已停用")
    try:
        job = await create_run(session, project, config, trigger="manual", actor=ctx.user_id)
    except StopRun as exc:
        raise HTTPException(409, str(exc)) from exc
    background.add_task(execute_run, job.id)
    return {"state": "queued", "message": "已排队", "job": run_payload(job, advisor=True)}


@router.get("/projects/{project_id}/search-visibility")
async def overview(project_id: int, tenant_id: int = Query(...),
                   ctx: AuthContext = Depends(require_scoped_auth),
                   session: AsyncSession = Depends(get_session)):
    _, config = await load_project(session, ctx, tenant_id, project_id)
    state = access_state(config, ctx)
    if state["state"] != "ready":
        return {**state, "notice": NOTICE}
    rows = list(await session.scalars(select(GeoAsyncJob).where(
        GeoAsyncJob.kind == KIND, GeoAsyncJob.tenant_id == tenant_id,
        GeoAsyncJob.ref_type == "geo_project", GeoAsyncJob.ref_id == project_id,
    ).order_by(GeoAsyncJob.created_at.desc(), GeoAsyncJob.id.desc()).limit(100)))
    latest = run_payload(rows[0], advisor=is_advisor(ctx)) if rows else None
    weeks = {}
    from datetime import timedelta
    start = week_start() - timedelta(weeks=11)
    for row in rows:
        if row.created_at < start:
            continue
        key = week_start(row.created_at).isoformat()
        if key not in weeks:
            payload = run_payload(row, advisor=is_advisor(ctx))
            weeks[key] = {"week": payload["created_at"][:10], "status": row.status,
                          "summary": payload["result"].get("summary", {})}
    return {**state, "notice": NOTICE, "latest": latest, "weeks": list(reversed(weeks.values()))}


async def visible_job(session, ctx, tenant_id, project_id, job_id):
    _, config = await load_project(session, ctx, tenant_id, project_id)
    state = access_state(config, ctx)
    if state["state"] != "ready":
        return state, None
    row = await session.get(GeoAsyncJob, job_id)
    if row is None or row.kind != KIND or row.tenant_id != tenant_id or row.ref_type != "geo_project" or row.ref_id != project_id:
        raise HTTPException(404, "本次查询不存在")
    return state, run_payload(row, advisor=is_advisor(ctx))


@router.get("/projects/{project_id}/search-visibility/runs/{job_id}")
async def detail(project_id: int, job_id: int, tenant_id: int = Query(...),
                 ctx: AuthContext = Depends(require_scoped_auth),
                 session: AsyncSession = Depends(get_session)):
    state, job = await visible_job(session, ctx, tenant_id, project_id, job_id)
    return {**state, "job": job} if job else state


@router.get("/projects/{project_id}/search-visibility/runs/{job_id}/csv")
async def download(project_id: int, job_id: int, tenant_id: int = Query(...),
                   ctx: AuthContext = Depends(require_scoped_auth),
                   session: AsyncSession = Depends(get_session)):
    state, job = await visible_job(session, ctx, tenant_id, project_id, job_id)
    if job is None:
        return state
    return Response(csv_text(job), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="deepseek-visibility-{job_id}.csv"',
        "Cache-Control": "no-store",
    })


@router.get("/search-visibility/usage")
async def usage(ctx: AuthContext = Depends(require_scoped_auth),
                session: AsyncSession = Depends(get_session)):
    if not is_admin(ctx):
        raise HTTPException(403, "仅超管可查看全平台用量")
    settings = get_settings()
    return {**await month_usage(session), "limit_cny": settings.deepseek_search_monthly_limit_cny,
            "state": "ready" if settings.deepseek_search_api_key.strip() else "not_enabled"}
