"""Workbench execution projection. GET never advances a job or calls a provider."""
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, PositiveInt
from sqlalchemy import func, select

from app.models.module_workspace import SeoSite
from app.models.seo_cockpit import SeoTask
from app.module_scope import ensure_module_access, seo_site_is_operational
from app.seo_content_workflow import schema_ready
from app.seo_demo_source import get_seo_session as get_session, require_seo_scoped_auth as require_scoped_auth
from app.seo_service_plan import service_plan_is_paused
from app.seo_service_workflows import KINDS, PERMISSIONS, advance_service_workflow, execute_diagnosis_page, reserve_service_workflow

router = APIRouter()
EXECUTION_PERMISSIONS = {"content_delivery": "seo.content", **PERMISSIONS}


class ServiceCycleTrigger(BaseModel):
    tenant_id: PositiveInt
    site_id: PositiveInt
    kind: Literal["website", "monitoring", "report"]
    expected_revision: int = Field(ge=1)
    request_id: UUID


class ServiceCycleAdvance(BaseModel):
    tenant_id: PositiveInt
    site_id: PositiveInt
    retry_page_id: PositiveInt | None = None
    explanation: str | None = Field(None, min_length=1, max_length=4000)
    report_sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")
    retry_analytics_source: Literal["baidu_tongji", "ga4"] | None = None
    allow_incomplete_analytics: bool = False


async def read_scope(session, ctx, tenant_id, site_id):
    ctx.ensure_tenant(tenant_id)
    if not (ctx.can_view("seo.site") and ctx.can_view("seo.content")):
        raise HTTPException(403, "执行进度需要内容与网站查看权限")
    await ensure_module_access(session, ctx, tenant_id, "seo")
    site = await session.get(SeoSite, site_id)
    if not site or site.tenant_id != tenant_id:
        raise HTTPException(404, "SEO 网站不存在")
    return site


async def execution(session, ctx, task_id, tenant_id, site_id):
    task = await session.get(SeoTask, task_id)
    if not task or task.tenant_id != tenant_id or task.site_id != site_id or task.action_type not in EXECUTION_PERMISSIONS:
        raise HTTPException(404, "SEO 执行链不存在")
    if not ctx.can_view(EXECUTION_PERMISSIONS[task.action_type]):
        raise HTTPException(403, "没有对应执行链的查看权限")
    return task


async def can_operate(session, ctx, site):
    from app.api.seo import _site_advisor_assignment
    if ctx.user_id is None or not (ctx.can_edit("seo.site") and ctx.can_edit("seo.content")):
        return False
    if not await schema_ready(session) or not await seo_site_is_operational(session, site.tenant_id, site.id):
        return False
    return await _site_advisor_assignment(session, site.tenant_id, site.id, ctx.user_id, schema_ready=True) is not None


def projection(task, site, ctx, authorized, *, read_only=True):
    from app.api.seo_cockpit import payload
    result = payload(task)
    params = {**task.params}
    if params.get("incremental"):
        params["incremental"] = {k: v for k, v in params["incremental"].items() if k != "token"}
    from app.seo_notifications import visible_events
    result["notifications"] = visible_events(task, ctx, site, authorized)
    params.pop("notification_outbox", None)
    if params.get("report"):
        params["report"] = {k: v for k, v in params["report"].items() if k != "html"}
    result["params"] = params
    permitted = authorized and ctx.can_edit(EXECUTION_PERMISSIONS[task.action_type]) and task.status not in {"done", "cancelled"}
    may_advance = permitted and not service_plan_is_paused(site)
    retry_ids = [int(key) for key, value in params.get("pages", {}).items() if value["state"] == "failed"]
    result["allowed_actions"] = {"advance": may_advance, "cancel": permitted,
        "retry_page_ids": retry_ids if may_advance else [],
        "explain_report": bool(may_advance and params.get("report"))}
    from app.seo_analytics_cycles import public_cycles
    result["allowed_actions"]["retry_analytics_sources"] = sorted({c["source"] for c in public_cycles(site)
        if may_advance and task.action_type == KINDS["report"] and not params.get("report")
        and (c.get("month") == params.get("month") or c.get("state") == "authorization_required")
        and c.get("state") in {"retry_wait", "authorization_required", "needs_attention", "discarded"}})
    result["allowed_actions"]["prepare_incomplete_report"] = bool(may_advance and task.action_type == KINDS["report"]
        and not params.get("report") and params.get("blocker") == "analytics_source_requires_advisor")
    stem = f"/api/v1/seo/workbench/executions/{task.id}"
    result["links"] = {"detail": f"{stem}?tenant_id={site.tenant_id}&site_id={site.id}",
        "advance": f"/api/v1/seo/workbench/content-workflows/{task.id}/advance" if task.action_type == "content_delivery" else f"{stem}/advance",
        "cancel": stem,
        "report": f"{stem}/report?tenant_id={site.tenant_id}&site_id={site.id}" if params.get("report") else None}
    if params.get("content_id"):
        result["links"]["content_delivery"] = f"/api/v1/seo/workbench/content-assets/{params['content_id']}/delivery?tenant_id={site.tenant_id}&site_id={site.id}"
    result["effective_pause"] = service_plan_is_paused(site)
    result["read_only"] = read_only
    return result


@router.get("/workbench/executions")
async def list_executions(tenant_id: PositiveInt, site_id: PositiveInt,
                          page: int = Query(1, ge=1, le=10000), page_size: int = Query(20, ge=1, le=100),
                          session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    site = await read_scope(session, ctx, tenant_id, site_id)
    actions = [key for key, permission in EXECUTION_PERMISSIONS.items() if ctx.can_view(permission)]
    filters = (SeoTask.tenant_id == tenant_id, SeoTask.site_id == site_id, SeoTask.action_type.in_(actions))
    total = int(await session.scalar(select(func.count()).select_from(SeoTask).where(*filters)) or 0)
    tasks = list(await session.scalars(select(SeoTask).where(*filters).order_by(SeoTask.id.desc()).offset((page - 1) * page_size).limit(page_size)))
    authorized = await can_operate(session, ctx, site)
    cursors = (site.site_settings or {}).get("seo_service_cycle_cursors") or {}
    cycles = {kind: {key: value for key, value in cursor.items()
                     if key in {"sequence", "month", "last_checked_at", "next_due_at", "task_id", "blocker"}}
              for kind, cursor in cursors.items() if kind in KINDS and ctx.can_view(PERMISSIONS[KINDS[kind]])}
    from app.seo_workflow_capabilities import trigger_capabilities
    from app.seo_analytics_cycles import public_cycles
    return {"items": [projection(task, site, ctx, authorized) for task in tasks], "total": total,
        "trigger_actions": await trigger_capabilities(session, ctx, site),
        "cycles": cycles, "analytics_cycles": public_cycles(site), "page": page, "page_size": page_size,
        "read_only": True, "as_of": datetime.now(timezone.utc).isoformat()}


@router.get("/workbench/executions/{task_id}")
async def get_execution(task_id: int, tenant_id: PositiveInt, site_id: PositiveInt,
                        session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    site = await read_scope(session, ctx, tenant_id, site_id)
    task = await execution(session, ctx, task_id, tenant_id, site_id)
    return projection(task, site, ctx, await can_operate(session, ctx, site))


@router.get("/workbench/executions/{task_id}/report")
async def read_report(task_id: int, tenant_id: PositiveInt, site_id: PositiveInt,
                      session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    await read_scope(session, ctx, tenant_id, site_id)
    task = await execution(session, ctx, task_id, tenant_id, site_id)
    report = task.params.get("report")
    if not report or task.action_type != KINDS["report"]:
        raise HTTPException(404, "该任务尚无已生成报告")
    return Response(report["html"], media_type="text/html", headers={"Cache-Control": "private, no-store",
        "Content-Disposition": f'attachment; filename="seo-report-{task.id}.html"',
        "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'",
        "X-Content-Type-Options": "nosniff", "ETag": '"' + report["sha256"] + '"'})


@router.post("/workbench/service-cycles/run")
async def trigger_service_cycle(req: ServiceCycleTrigger, session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    from app.api.seo import _content_workflow_site, _service_plan_payload
    from app.api.seo_cockpit import payload
    site = await _content_workflow_site(session, ctx, req.tenant_id, req.site_id)
    if not ctx.can_edit(PERMISSIONS[KINDS[req.kind]]):
        raise HTTPException(403, "没有对应周期任务的编辑权限")
    key = "request:" + str(req.request_id)
    existing = await session.scalar(select(SeoTask).where(
        SeoTask.tenant_id == req.tenant_id, SeoTask.site_id == req.site_id, SeoTask.action_type == KINDS[req.kind],
        SeoTask.params["request_key"].as_string() == key).limit(1))
    if existing:
        return {"created": False, "task": payload(existing)}
    if _service_plan_payload(site)["revision"] != req.expected_revision:
        raise HTTPException(409, {"code": "service_plan_version_conflict"})
    task, created = await reserve_service_workflow(session, site, req.kind, key, ctx.user_id)
    await session.commit()
    await session.refresh(task)
    return {"created": created, "task": payload(task)}


@router.post("/workbench/executions/{task_id}/advance")
async def advance_execution(task_id: int, req: ServiceCycleAdvance, background_tasks: BackgroundTasks,
                            session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    from app.api.seo import _content_workflow_site
    site = await _content_workflow_site(session, ctx, req.tenant_id, req.site_id)
    task = await session.get(SeoTask, task_id, with_for_update=True)
    if not task or task.tenant_id != req.tenant_id or task.site_id != req.site_id or task.action_type not in PERMISSIONS:
        raise HTTPException(404, "周期执行链不存在")
    if not ctx.can_edit(PERMISSIONS[task.action_type]):
        raise HTTPException(403, "没有对应执行链编辑权限")
    if req.explanation is not None and (task.action_type != KINDS["report"] or not req.explanation.strip()):
        raise HTTPException(422, "顾问说明仅用于报告且不能只有空白")
    if req.retry_page_id is not None and task.action_type != KINDS["website"]:
        raise HTTPException(422, "仅网站诊断可以重试单页")
    if req.retry_analytics_source is not None:
        if task.action_type != KINDS["report"] or task.params.get("report") or task.status not in {"open", "in_progress"}:
            raise HTTPException(409, "仅未冻结报告的取数步骤可以重试")
        if service_plan_is_paused(site):
            raise HTTPException(409, "服务计划已暂停")
        from app.seo_analytics_cycles import cycle_enabled
        if not cycle_enabled(site):
            raise HTTPException(409, "请先在服务计划开启周期取数")
        from app.models.seo_site_analytics import SeoSiteAnalyticsSource
        configured = await session.scalar(select(SeoSiteAnalyticsSource.id).where(
            SeoSiteAnalyticsSource.tenant_id == site.tenant_id, SeoSiteAnalyticsSource.site_id == site.id,
            SeoSiteAnalyticsSource.source == req.retry_analytics_source, SeoSiteAnalyticsSource.enabled.is_(True)))
        if configured is None:
            raise HTTPException(404, "该网站未启用此数据源")
        settings = dict(site.site_settings or {})
        cycles = dict(settings.get("seo_analytics_cycles") or {})
        key = f"{req.retry_analytics_source}:{task.params['month']}"
        cursor = cycles.get(key) or {}
        from app.seo_content_workflow import utc
        if cursor.get("state") == "running" and utc(datetime.fromisoformat(cursor["lease_until"])) > datetime.now(timezone.utc):
            raise HTTPException(409, "取数请求仍在执行，请等待结果")
        cycles.pop(key, None)
        # A source-level authorization failure can originate in another month.
        # The advisor's explicit retry releases that block as well.
        cycles = {k: c for k, c in cycles.items() if not (
            c.get('source') == req.retry_analytics_source and c.get('state') == 'authorization_required')}
        settings["seo_analytics_cycles"] = cycles
        site.site_settings = settings
    if req.allow_incomplete_analytics and task.action_type != KINDS["report"]:
        raise HTTPException(422, "缺项说明仅用于报告")
    await advance_service_workflow(session, site, task, explanation=req.explanation,
        report_sha256=req.report_sha256, actor_id=ctx.user_id, retry_page_id=req.retry_page_id,
        allow_incomplete_analytics=req.allow_incomplete_analytics)
    await session.commit()
    await session.refresh(task)
    if task.action_type == KINDS["website"] and not service_plan_is_paused(site) and task.status == "in_progress":
        background_tasks.add_task(execute_diagnosis_page, task.id)
    return projection(task, site, ctx, True, read_only=False)


@router.get("/workbench/notifications")
async def list_notifications(tenant_id: PositiveInt, site_id: PositiveInt,
                              session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    site = await read_scope(session, ctx, tenant_id, site_id)
    authorized = await can_operate(session, ctx, site)
    from app.seo_notifications import visible_events
    actions = [key for key, permission in EXECUTION_PERMISSIONS.items() if ctx.can_view(permission)]
    tasks = list(await session.scalars(select(SeoTask).where(SeoTask.tenant_id == tenant_id,
        SeoTask.site_id == site_id, SeoTask.action_type.in_(actions), SeoTask.status.in_(("open", "in_progress")))
        .order_by(SeoTask.updated_at.desc(), SeoTask.id.desc()).limit(101)))
    return {"items": [event for task in tasks[:100] for event in visible_events(task, ctx, site, authorized)],
            "truncated": len(tasks) > 100, "channel": "in_app", "read_only": True}


class NotificationRead(BaseModel):
    tenant_id: PositiveInt
    site_id: PositiveInt
    task_id: PositiveInt
    event_id: UUID


@router.post("/workbench/notifications/read")
async def read_notification(req: NotificationRead, session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    await read_scope(session, ctx, req.tenant_id, req.site_id)
    site = await session.get(SeoSite, req.site_id, with_for_update=True)
    task = await session.get(SeoTask, req.task_id, with_for_update=True)
    if not task or task.tenant_id != req.tenant_id or task.site_id != req.site_id or task.action_type not in EXECUTION_PERMISSIONS:
        raise HTTPException(404, "提醒不存在")
    if not ctx.can_view(EXECUTION_PERMISSIONS[task.action_type]):
        raise HTTPException(403, "没有对应执行链的查看权限")
    from app.seo_notifications import acknowledge
    acknowledge(task, ctx, site, await can_operate(session, ctx, site), str(req.event_id), datetime.now(timezone.utc))
    await session.commit()
    return {"event_id": str(req.event_id), "read": True}


@router.delete("/workbench/executions/{task_id}")
async def cancel_execution(task_id: int, tenant_id: PositiveInt, site_id: PositiveInt,
                           session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    from app.api.seo import _content_workflow_site
    site = await _content_workflow_site(session, ctx, tenant_id, site_id)
    task = await session.get(SeoTask, task_id, with_for_update=True)
    if not task or task.tenant_id != tenant_id or task.site_id != site_id or task.action_type not in EXECUTION_PERMISSIONS:
        raise HTTPException(404, "执行链不存在")
    if not ctx.can_edit(EXECUTION_PERMISSIONS[task.action_type]):
        raise HTTPException(403, "没有对应执行链编辑权限")
    if task.status == "done":
        raise HTTPException(409, "已完成证据不能取消")
    task.status = "cancelled"
    task.params = {**task.params, "cancelled_by": ctx.user_id, "cancelled_at": datetime.now(timezone.utc).isoformat()}
    await session.commit()
    await session.refresh(task)
    return projection(task, site, ctx, True, read_only=False)
