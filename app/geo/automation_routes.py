"""GEO adapter for the shared advisor-controlled automation ledger."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime
import json
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.routing import APIRoute
from pydantic import PositiveInt
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app import automation_projects as control
from app import automation_project_v2 as control_v2
from app.automation_project_contract import Configure, Control
from app.automation_project_contract import ConfigurationV2
from app.database import async_session_factory, get_session
from app.geo import onsite_ai
from app.geo.content import async_jobs
from app import onsite_workflow as work
from app.geo.onsite_routes import PREFIX, _proposal_snapshot, enqueue_proposal_locked, scope as onsite_scope
from app.geo.project_workflows import PLAN_KEY, advisor_available, plan_for
from app.geo.project_scope import project_scope
from app.geo.automation_v2_adapter import (
    BRIEF_OPERATION, COMPETITOR_OPERATION, MASTER_OPERATION, ONSITE_OPERATION,
    OUTCOME_OPERATION, PERIODIC_OPERATION, PUBLICATION_OPERATION,
    SUPPORTED_OPERATIONS, VARIANT_OPERATION, VISIBILITY_OPERATION,
    live_basis, validate_configuration,
)
from app.geo.tenant_scope import ensure_geo_entitlement
from app.models import GeoActionTicket, GeoAsyncJob, GeoProject, GeoVisibilityPatrolRun
from app.models.user import User
from app.models.role import Role
from app.security.auth import require_scoped_auth

class AutomationRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                response = await original(request)
            except RequestValidationError:
                return JSONResponse(
                    status_code=422,
                    content={"detail": {"code": "automation_invalid_request", "message": "请求参数不符合自动执行契约"}},
                    headers={"Cache-Control": "no-store"},
                )
            except HTTPException as exc:
                headers = {**(exc.headers or {}), "Cache-Control": "no-store"}
                raise HTTPException(exc.status_code, exc.detail, headers=headers) from None
            except SQLAlchemyError:
                return JSONResponse(
                    status_code=503,
                    content={"detail": {"code": "automation_unavailable", "message": "自动执行记录暂不可用"}},
                    headers={"Cache-Control": "no-store"},
                )
            response.headers["Cache-Control"] = "no-store"
            return response

        return handler


router = APIRouter(
    prefix="/workbench/automation-projects", tags=["GEO 自动执行"],
    route_class=AutomationRoute,
)
health_router = APIRouter(tags=["GEO 自动执行"], route_class=AutomationRoute)

COVERAGE = {
    "controlled": ["configured_onsite_ai", "periodic_workflow", "visibility_patrol"],
    "not_controlled": [
        "manual_onsite_ai", "platform_publication", "distribution",
        "website_mutation", "approval", "acceptance",
    ],
}


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _health_unavailable() -> dict:
    return {
        "schema": 1, "module": "geo",
        "scope": {"kind": "global", "tenant_id": None},
        "as_of": control.now().isoformat(), "state": "unavailable",
        "contract_versions": [],
        "counts": {key: None for key in
                   ("projects", "runs", "pending_human", "unknown_cost")},
        "rows": [], "truncated": False,
        "queue": {"state": "unknown", "queued": None,
                  "running": None, "unknown": None},
        "worker": {"state": "unverified", "verified": False,
                   "last_tick_at": None, "evidence": None},
        "overall": "unavailable",
        "alerts": [{"code": "automation_health_unavailable",
                    "summary": "自动执行健康数据暂不可用"}],
    }


async def _authorized_scope(session, ctx, tenant_id: int, scope_id: int, *, write: bool):
    if ctx.user_id is None:
        raise HTTPException(403, "自动执行必须由实名顾问操作")
    return await onsite_scope(session, ctx, tenant_id, scope_id, write=write)


def _automatic_initial_blocker(value: dict) -> tuple[str, str] | None:
    """Project automation creates one first draft; revisions remain human-only."""
    if value.get("phase") != "draft":
        return "automation_task_not_draft", "任务已进入人工审核或实施阶段，请建立后续任务"
    if isinstance(value.get("ai_proposal"), dict):
        return "automation_existing_proposal", "任务已有待核对方案，不会自动覆盖"
    if isinstance(value.get("ai_run"), dict):
        return "automation_prior_ai_request", "任务已有 AI 请求记录，请人工核对后建立后续任务"
    if "save_proposal" not in work.allowed_actions(value, True):
        return "automation_task_ineligible", "所选任务当前不能生成待审方案"
    return None


async def _validate_tasks(session, project: GeoProject, task_ids: list[int]) -> None:
    rows = list(await session.scalars(select(GeoActionTicket).where(
        GeoActionTicket.tenant_id == project.tenant_id,
        GeoActionTicket.id.in_(task_ids),
        GeoActionTicket.advice_code.startswith(PREFIX),
    ).with_for_update()))
    indexed = {int(row.id): row for row in rows}
    if set(indexed) != set(task_ids):
        raise control.problem("automation_task_not_found", "所选站内任务不属于当前项目", 404)
    for task_id in task_ids:
        row = indexed[task_id]
        value = (row.progress or {}).get("onsite") or {}
        if value.get("project_id") != project.id:
            raise control.problem("automation_task_not_found", "所选站内任务不属于当前项目", 404)
        blocker = _automatic_initial_blocker(value)
        if blocker:
            raise control.problem(*blocker)
        snapshot = await _proposal_snapshot(session, project, row)
        onsite_ai.planning_preflight(snapshot)


async def _project_payload(session, key: dict, *, live_project=None, actor_id=None) -> dict:
    ready = await control.schema_ready(session)
    project = await control.read_project(session, key) if ready else None
    result = control.project_view(key, project, ready=ready, coverage=COVERAGE)
    result["capabilities"]["available_operations"] = sorted(SUPPORTED_OPERATIONS)
    configured = set()
    if project:
        config = project.get("configuration") or {}
        if config.get("contract_version") == 2:
            configured = set(config.get("operations") or [])
        elif "onsite_ai" in (config.get("operations") or []):
            configured = {"configured_onsite_ai"}
    all_known = {"configured_onsite_ai", *SUPPORTED_OPERATIONS,
                 "manual_onsite_ai", "platform_publication", "distribution",
                 "periodic_workflow", "website_mutation", "approval", "acceptance"}
    result["coverage"] = {"controlled": sorted(configured),
                          "not_controlled": sorted(all_known - configured)}
    if live_project is not None:
        result["scope_name"] = live_project.name
    owner_current = bool(
        project and live_project is not None and actor_id is not None
        and int(project["owner_user_id"]) == int(actor_id)
        and plan_for(live_project).get("advisor_user_id") == actor_id
        and await advisor_available(session, key["tenant_id"], actor_id)
    )
    if project and not owner_current:
        result["capabilities"]["can_configure"] = False
        result["capabilities"]["can_control"] = False
        result["allowed_actions"] = []
        result["blocker"] = "automation_owner_mismatch"
    return result


@router.get("")
async def list_projects(response: Response, tenant_id: PositiveInt | None = None,
                        before_scope_id: PositiveInt | None = None,
                        limit: int = Query(20, ge=1, le=50),
                        session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    _no_store(response)
    if ctx.user_id is None or not (ctx.can_edit("geo.assets") and ctx.can_edit("geo.content")):
        raise HTTPException(403, "需要实名 GEO 顾问及资产、内容编辑权限")
    if tenant_id is not None:
        ctx.ensure_tenant(tenant_id)
    query = select(GeoProject).where(
        GeoProject.status == "active",
        GeoProject.project_settings[PLAN_KEY]["advisor_user_id"].as_integer() == ctx.user_id,
    )
    if tenant_id is not None:
        query = query.where(GeoProject.tenant_id == tenant_id)
    if ctx.tenant_id is not None:
        query = query.where(GeoProject.tenant_id == ctx.tenant_id)
    if before_scope_id is not None:
        query = query.where(GeoProject.id < before_scope_id)
    candidates = list(await session.scalars(query.order_by(GeoProject.id.desc())))
    items = []
    for project in candidates:
        try:
            await ensure_geo_entitlement(session, project.tenant_id, allow_demo_read=False, lock_binding=False)
            await project_scope(session, project.tenant_id, project.id)
            if not await advisor_available(session, project.tenant_id, ctx.user_id):
                continue
            key = control.scope("geo", int(project.tenant_id), int(project.id))
            item = await _project_payload(
                session, key, live_project=project, actor_id=ctx.user_id
            )
            items.append(item)
            if len(items) > limit:
                break
        except HTTPException:
            continue
    return {"schema": 1, "module": "geo", "items": items[:limit],
            "next_before_scope_id": items[limit - 1]["scope_id"] if len(items) > limit else None}


@router.get("/{scope_id}/control")
async def get_control(scope_id: PositiveInt, tenant_id: PositiveInt, response: Response,
                      session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    _no_store(response)
    project = await _authorized_scope(session, ctx, tenant_id, scope_id, write=False)
    return await _project_payload(
        session, control.scope("geo", tenant_id, scope_id),
        live_project=project, actor_id=ctx.user_id,
    )


@router.get("/{scope_id}/configuration-basis")
async def configuration_basis(scope_id: PositiveInt, tenant_id: PositiveInt,
                              operation: str, response: Response,
                              before_object_id: PositiveInt | None = None,
                              limit: int = Query(25, ge=1, le=50),
                              session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    """Read live hashes and variants; callers never manufacture source hashes."""
    _no_store(response)
    project = await _authorized_scope(session, ctx, tenant_id, scope_id, write=False)
    ready = await control_v2.schema_ready(session)
    base = {"schema": 1, "module": "geo", "tenant_id": tenant_id,
            "scope_id": scope_id, "contract_version": 2}
    if not ready:
        return {**base, "state": "schema_pending", "service_plan": None,
                "source_bindings": [], "available_operations": [], "targets": [],
                "next_before_object_id": None}
    if operation not in SUPPORTED_OPERATIONS:
        raise control.problem("automation_operation_not_supported", "所选 GEO 操作尚未接入受控执行", 409)
    basis = await live_basis(session, tenant_id, scope_id, [operation])
    grouped: dict[int, list[dict]] = {}
    for target in basis["targets_by_operation"][operation]:
        if before_object_id is None or target["object_id"] < before_object_id:
            grouped.setdefault(target["object_id"], []).append(target)
    object_ids = sorted(grouped, reverse=True)[:limit + 1]
    selected_ids = object_ids[:limit]
    targets = [target | {"label": next(
        (row.question for row in basis["prompts"] if int(row.id) == object_id), str(object_id)
    )[:240]} for object_id in selected_ids for target in grouped[object_id]]
    return {**base, "state": "ready", "service_plan": basis["service_plan"],
            "source_bindings": basis["source_bindings"],
            "available_operations": sorted(SUPPORTED_OPERATIONS), "targets": targets,
            "next_before_object_id": selected_ids[-1] if len(object_ids) > limit else None}


@router.put("/{scope_id}/control")
async def configure(scope_id: PositiveInt, req: Configure, response: Response,
                    session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    _no_store(response)
    # The parent GEO entitlement dependency performs a read lock.  Close that
    # read transaction before taking shared automation locks, then revalidate
    # entitlement below in the documented shared->module lock order.
    await session.rollback()
    await _authorized_scope(session, ctx, req.tenant_id, scope_id, write=False)
    key = control.scope("geo", req.tenant_id, scope_id)
    await control.require_schema(session)
    row, replayed, _ = await control.configure_project(session, key, req, int(ctx.user_id))
    project = await _authorized_scope(session, ctx, req.tenant_id, scope_id, write=True)
    if not replayed:
        if isinstance(req.configuration, ConfigurationV2):
            await validate_configuration(
                session, req.tenant_id, scope_id, req.configuration, int(ctx.user_id)
            )
        else:
            await _validate_tasks(session, project, req.configuration.task_ids)
    await session.commit()
    return {**(await _project_payload(
        session, key, live_project=project, actor_id=ctx.user_id
    )), "replayed": replayed}


async def _cancel_current_child(session, key: dict, project) -> None:
    if not project or not project.get("current_run_id"):
        return
    run = await control.read_run(session, key, project["current_run_id"])
    if not run:
        return
    running = next((step for step in run["steps"] if step["status"] == "running"), None)
    if not running:
        return
    job = await session.scalar(select(GeoAsyncJob).where(
        GeoAsyncJob.tenant_id == key["tenant_id"],
        GeoAsyncJob.kind == async_jobs.KIND_ONSITE_PROPOSAL,
        GeoAsyncJob.ref_id == running["task_id"],
        GeoAsyncJob.request_meta["request_id"].as_string() == running["request_id"],
    ).order_by(GeoAsyncJob.id.desc()).limit(1).with_for_update())
    if job:
        meta = dict(job.request_meta or {})
        meta["cancel_requested"] = True
        job.request_meta = meta
        if job.status == "pending":
            job.status = "cancelled"
            from datetime import datetime
            job.finished_at = datetime.utcnow()
            token = {**key, "run_id": str(run["id"]), "generation": int(run["generation"]),
                     "step_key": running["step_key"], "task_id": running["task_id"],
                     "request_id": running["request_id"], "owner_user_id": int(project["owner_user_id"])}
            await control.settle_step(
                session, token, status="cancelled", error_code="automation_cancelled",
                fee_state="not_called",
            )


async def _bind_child_job(session, token: dict, job_id: int) -> None:
    """Bind the shared step to the exact durable child in the same commit."""
    _, run, _ = await control.check_step(session, token)
    steps = deepcopy(run["steps"])
    step = next(item for item in steps if item["step_key"] == token["step_key"])
    if step.get("job_id") not in {None, job_id}:
        raise control.problem("automation_step_stale", "自动步骤已关联其他持久作业")
    step["claim_generation"] = int(token["generation"])
    step["job_id"] = int(job_id)
    await session.execute(text(
        "UPDATE automation_project_runs SET steps=CAST(:steps AS jsonb) WHERE id=CAST(:id AS uuid)"
    ), {"id": token["run_id"], "steps": json.dumps(steps)})
    await control.append_event(
        session, control.scope("geo", token["tenant_id"], token["scope_id"]),
        run_id=token["run_id"], code="step_job_queued", step_key=token["step_key"],
        request_id=token["request_id"], fee_state="not_called",
    )


async def _bind_patrol_run(session, token: dict, patrol_run_id: int) -> None:
    _, run, _ = await control.check_step(session, token)
    steps = deepcopy(run["steps"])
    step = next(item for item in steps if item["step_key"] == token["step_key"])
    if step.get("patrol_run_id") not in {None, patrol_run_id}:
        raise control.problem("automation_step_stale", "自动步骤已关联其他巡检")
    step["claim_generation"] = int(token["generation"])
    step["patrol_run_id"] = int(patrol_run_id)
    await session.execute(text(
        "UPDATE automation_project_runs SET steps=CAST(:steps AS jsonb) WHERE id=CAST(:id AS uuid)"
    ), {"id": token["run_id"], "steps": json.dumps(steps)})
    await control.append_event(
        session, control.scope("geo", token["tenant_id"], token["scope_id"]),
        run_id=token["run_id"], code="step_patrol_queued", step_key=token["step_key"],
        request_id=token["request_id"], fee_state="not_called",
    )


async def _finish_patrol_step(key: dict, run_id: str, token: dict,
                              patrol_run_id: int) -> None:
    from app.geo.content.patrol import execute_patrol_run_owned
    async with async_session_factory() as session:
        patrol = await execute_patrol_run_owned(session, patrol_run_id, key["tenant_id"])
        summary = patrol.summary if isinstance(patrol.summary, dict) else {}
        status = ("succeeded" if patrol.status == "completed"
                  and int(summary.get("cells_ok") or 0) > 0
                  and int(summary.get("cells_fail") or 0) == 0 else "blocked")
        from app.geo.automation_v2_adapter import aggregate_step_fee
        current_run = await control.read_run(session, key, token["run_id"])
        current_step = next((item for item in (current_run or {}).get("steps", [])
                             if item.get("request_id") == token["request_id"]), None)
        fee_state = aggregate_step_fee(current_step)
        await control.settle_step(
            session, token, status=status,
            error_code=None if status == "succeeded" else "automation_patrol_failed",
            evidence_refs=(f"geo_patrol_run:{patrol_run_id}",),
            result_links=(f"/api/v1/geo/visibility-patrol/runs/{patrol_run_id}?tenant_id={key['tenant_id']}",),
            fee_state=fee_state,
        )
        await session.commit()
    await run_automation(key, run_id)


async def _finish_periodic_step(key: dict, run_id: str, token: dict) -> None:
    from app.geo.project_workflows import refresh_project
    await refresh_project(key["scope_id"], automation_token=token)
    async with async_session_factory() as session:
        await control.settle_step(
            session, token, status="succeeded", fee_state="not_called",
            evidence_refs=(f"geo_project:{key['scope_id']}",),
            result_links=(f"/api/v1/geo/workbench/automation-projects/{key['scope_id']}/control?tenant_id={key['tenant_id']}",),
        )
        await session.commit()
    await run_automation(key, run_id)


async def _finish_outcome_step(key: dict, run_id: str, token: dict) -> None:
    from app.geo.outcome_review import update_outcome_review
    try:
        async with async_session_factory() as session:
            updated = await update_outcome_review(
                session, int(token["target"]["object_id"]), tenant_id=key["tenant_id"],
                automation_token=token,
            )
            if not updated:
                raise control.problem("automation_target_changed", "复盘任务已变化，请刷新")
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        async with async_session_factory() as session:
            await control.settle_step(
                session, token, status="blocked",
                error_code=detail.get("code") or "automation_outcome_review_blocked",
                fee_state="not_called",
            )
            await session.commit()
        await run_automation(key, run_id)
        return
    async with async_session_factory() as session:
        await control.settle_step(
            session, token, status="succeeded", fee_state="not_called",
            evidence_refs=(f"geo_ticket:{token['target']['object_id']}",),
            result_links=(f"/api/v1/geo/action-tickets/{token['target']['object_id']}?tenant_id={key['tenant_id']}",),
        )
        await session.commit()
    await run_automation(key, run_id)


async def _finish_publication_step(key: dict, run_id: str, token: dict) -> None:
    from app.geo.publication_monitor import check_publication_controlled
    try:
        async with async_session_factory() as session:
            await check_publication_controlled(
                session, key["tenant_id"], key["scope_id"], token
            )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        async with async_session_factory() as session:
            await control.settle_step(
                session, token, status="blocked",
                error_code=detail.get("code") or "automation_publication_monitor_blocked",
                fee_state="not_called",
            )
            await session.commit()
        await run_automation(key, run_id)
        return
    async with async_session_factory() as session:
        run = await control.read_run(session, key, token["run_id"])
        step = next((item for item in (run or {}).get("steps", [])
                     if item.get("request_id") == token["request_id"]), None)
        fee_state = "not_called" if not (step or {}).get("calls") else "not_called"
        await control.settle_step(
            session, token, status="succeeded", fee_state=fee_state,
            evidence_refs=(f"geo_publication:{token['target']['object_id']}",),
            result_links=(),
            success_actor_kind="system",
        )
        await session.commit()
    await run_automation(key, run_id)


@router.post("/{scope_id}/control")
async def act(scope_id: PositiveInt, req: Control, response: Response,
              background_tasks: BackgroundTasks,
              session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    _no_store(response)
    await session.rollback()
    await _authorized_scope(session, ctx, req.tenant_id, scope_id, write=False)
    key = control.scope("geo", req.tenant_id, scope_id)
    before = await control.read_project(session, key) if await control.schema_ready(session) else None
    if (not before or before.get("configuration", {}).get("contract_version") != 2):
        pending_targets = None
    elif req.action == "resume" and before.get("current_run_id"):
        prior_run = await control.read_run(session, key, before["current_run_id"])
        pending_targets = [step["target"] for step in (prior_run or {}).get("steps", [])
                           if step.get("status") == "pending" and isinstance(step.get("target"), dict)]
        await validate_configuration(
            session, req.tenant_id, scope_id,
            ConfigurationV2.model_validate(before["configuration"]), int(ctx.user_id),
            current_targets=pending_targets,
        )
    row, replayed, _ = await control.control_project(session, key, req, int(ctx.user_id))
    project = await _authorized_scope(session, ctx, req.tenant_id, scope_id, write=True)
    if not replayed and req.action == "start":
        if row["configuration"].get("contract_version") == 2:
            await validate_configuration(
                session, req.tenant_id, scope_id,
                ConfigurationV2.model_validate(row["configuration"]), int(ctx.user_id),
            )
        else:
            await _validate_tasks(session, project, row["configuration"]["task_ids"])
    if not replayed and req.action in {"pause", "takeover", "end"}:
        await _cancel_current_child(session, key, before)
    await session.commit()
    current = await control.read_project(session, key)
    if not replayed and req.action in {"start", "resume"} and current.get("current_run_id"):
        background_tasks.add_task(run_automation, key, str(current["current_run_id"]))
    return {**(await _project_payload(
        session, key, live_project=project, actor_id=ctx.user_id
    )), "replayed": replayed}


@router.get("/{scope_id}/runs")
async def run_history(scope_id: PositiveInt, tenant_id: PositiveInt, response: Response,
                      before_run_id: UUID | None = None, limit: int = Query(20, ge=1, le=50),
                      session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    _no_store(response)
    await _authorized_scope(session, ctx, tenant_id, scope_id, write=False)
    await control.require_schema(session)
    return await control.runs_page(session, control.scope("geo", tenant_id, scope_id), before_run_id, limit)


@router.get("/{scope_id}/runs/{run_id}")
async def get_run(scope_id: PositiveInt, run_id: UUID, tenant_id: PositiveInt, response: Response,
                  session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    _no_store(response)
    await _authorized_scope(session, ctx, tenant_id, scope_id, write=False)
    key = control.scope("geo", tenant_id, scope_id)
    await control.require_schema(session)
    return control.run_view(key, await control.read_run(session, key, run_id))


@router.get("/{scope_id}/runs/{run_id}/events")
async def run_events(scope_id: PositiveInt, run_id: UUID, tenant_id: PositiveInt, response: Response,
                     after_id: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                     session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    _no_store(response)
    await _authorized_scope(session, ctx, tenant_id, scope_id, write=False)
    await control.require_schema(session)
    return await control.events_page(session, control.scope("geo", tenant_id, scope_id), run_id, after_id, limit)


@router.get("/{scope_id}/events")
async def project_events(scope_id: PositiveInt, tenant_id: PositiveInt, response: Response,
                         after_id: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                         session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    _no_store(response)
    await _authorized_scope(session, ctx, tenant_id, scope_id, write=False)
    await control.require_schema(session)
    return await control.project_events_page(session, control.scope("geo", tenant_id, scope_id), after_id, limit)


@router.get("/{scope_id}/events/export")
async def export_events(scope_id: PositiveInt, tenant_id: PositiveInt, response: Response,
                        format: str = Query("json", pattern="^(json|csv)$"),
                        after_id: int = Query(0, ge=0), through_id: int | None = Query(None, ge=0),
                        limit: int = Query(100, ge=1, le=500),
                        session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    _no_store(response)
    await _authorized_scope(session, ctx, tenant_id, scope_id, write=False)
    page = await control_v2.events_export_page(
        session, control.scope("geo", tenant_id, scope_id),
        after_id=after_id, through_id=through_id, limit=limit,
    )
    if format == "csv":
        return PlainTextResponse(control_v2.csv_export(page), media_type="text/csv; charset=utf-8",
                                 headers={"Cache-Control": "no-store"})
    return page


@health_router.get("/workbench/automation-health")
async def automation_health(response: Response, session=Depends(get_session),
                            ctx=Depends(require_scoped_auth)):
    _no_store(response)
    # JWT contexts intentionally never set is_superadmin; that flag belongs to
    # the anonymous admin API-key fallback, which this endpoint rejects.
    if (ctx.user_id is None or ctx.tenant_id is not None
            or not ctx.can_edit("settings.accounts")
            or not ctx.can_edit("settings.customers")):
        raise HTTPException(403, "仅平台超管可读取全局自动执行健康状态")
    try:
        user = await session.get(User, int(ctx.user_id), populate_existing=True)
        role = await session.get(Role, user.role_id, populate_existing=True) if user and user.is_active else None
        permissions = role.permissions if role else {}
        if (user is None or user.tenant_id is not None
                or permissions.get("settings.accounts") != "edit"
                or permissions.get("settings.customers") != "edit"):
            raise HTTPException(403, "当前数据库身份不再具备平台超管权限")
        from app.geo.content.geo_scheduler import scheduler_runtime_status
        runtime = scheduler_runtime_status()
        worker = {"state": runtime.get("state") or "unverified", "verified": False,
                  "last_tick_at": runtime.get("last_success_at"),
                  "evidence": runtime.get("ownership")}
        return await control_v2.health_snapshot(session, "geo", worker=worker)
    except SQLAlchemyError as exc:
        return JSONResponse(
            status_code=503, content=_health_unavailable(),
            headers={"Cache-Control": "no-store"},
        )


async def run_automation(key: dict, run_id: str) -> None:
    """Claim exactly one step and atomically attach it to the durable GEO queue."""
    job_id = None
    continue_after_block = False
    try:
        async with async_session_factory() as session:
            token = await control.claim_step(session, key)
            if token is None or token["run_id"] != run_id:
                await session.commit()
                return
            try:
                await ensure_geo_entitlement(
                    session, key["tenant_id"], allow_demo_read=False, lock_binding=True
                )
                project = await session.get(
                    GeoProject, key["scope_id"], with_for_update=True, populate_existing=True
                )
                if (project is None or project.tenant_id != key["tenant_id"] or project.status != "active"
                        or plan_for(project).get("advisor_user_id") != token["owner_user_id"]
                        or not await advisor_available(
                            session, key["tenant_id"], token["owner_user_id"], lock=True
                        )):
                    raise control.problem(
                        "automation_owner_unavailable", "当前顾问分配或权限已变化", 403
                    )
                if token.get("operation") in SUPPORTED_OPERATIONS:
                    stored = await control.read_project(session, key)
                    await validate_configuration(
                        session, key["tenant_id"], key["scope_id"],
                        ConfigurationV2.model_validate(stored["configuration"]),
                        int(token["owner_user_id"]),
                        current_targets=[token["target"]],
                    )
                    if token.get("operation") == VISIBILITY_OPERATION:
                        target = token["target"]
                        patrol = GeoVisibilityPatrolRun(
                            tenant_id=key["tenant_id"], status="pending", trigger="schedule",
                            auto_persist=True, prefer_real=True, prompt_limit=1,
                            engine_keys=[target["variant"]], created_by=token["owner_user_id"],
                            summary={"automation_token": token},
                        )
                        session.add(patrol)
                        await session.flush()
                        await _bind_patrol_run(session, token, int(patrol.id))
                        patrol_id = int(patrol.id)
                    elif token.get("operation") == BRIEF_OPERATION:
                        from app.geo.content.brief_suggest import suggest_brief_heuristic
                        from app.geo.content.business_profile import display_brand, profile_brief_hints
                        from app.models import GeoContentTask, GeoPrompt, GeoOptimizationBusiness
                        target = token["target"]
                        task = await session.scalar(select(GeoContentTask).where(
                            GeoContentTask.id == target["object_id"],
                            GeoContentTask.tenant_id == key["tenant_id"],
                            GeoContentTask.status.notin_(("archived", "cancelled")),
                        ).with_for_update().execution_options(populate_existing=True))
                        if task is None:
                            raise control.problem("automation_target_changed", "内容任务已变化，请刷新")
                        prompt = await session.scalar(select(GeoPrompt).where(
                            GeoPrompt.id == task.prompt_id,
                            GeoPrompt.tenant_id == key["tenant_id"],
                        ).execution_options(populate_existing=True))
                        business = (await session.get(GeoOptimizationBusiness, task.business_id,
                                                       populate_existing=True)
                                    if task.business_id else None)
                        hints = profile_brief_hints(business.profile if business else None)
                        brand = display_brand(business.profile if business else None, fallback="本品牌")
                        suggested = suggest_brief_heuristic(
                            question=prompt.question, brand=brand,
                            existing=task.brief or {}, profile_hints=hints,
                        )
                        child = GeoAsyncJob(
                            tenant_id=key["tenant_id"], kind="automation_brief_suggestion",
                            status="succeeded", ref_type="content_task", ref_id=task.id,
                            request_meta={"request_id": token["request_id"],
                                          "automation_run_id": token["run_id"]},
                            result_meta={"schema": 1, "persisted": False,
                                         "suggested_brief": suggested},
                            created_by=token["owner_user_id"], started_at=datetime.utcnow(),
                            finished_at=datetime.utcnow(),
                        )
                        session.add(child)
                        await session.flush()
                        await _bind_child_job(session, token, int(child.id))
                        await control.settle_step(
                            session, token, status="succeeded", fee_state="not_called",
                            evidence_refs=(f"geo_async_job:{child.id}",),
                            result_links=(f"/api/v1/geo/content/async-jobs/{child.id}?tenant_id={key['tenant_id']}",),
                        )
                        brief_job_id = int(child.id)
                    elif token.get("operation") == COMPETITOR_OPERATION:
                        from app.geo.content.competitor_trace import (
                            build_competitor_report_markdown, build_competitor_trace,
                        )
                        from app.models import GeoAnswerSnapshot, GeoCompetitorAlias
                        target = token["target"]
                        alias = await session.scalar(select(GeoCompetitorAlias).where(
                            GeoCompetitorAlias.id == target["object_id"],
                            GeoCompetitorAlias.tenant_id == key["tenant_id"],
                        ).execution_options(populate_existing=True))
                        if alias is None:
                            raise control.problem("automation_target_changed", "竞品别名已变化，请刷新")
                        basis = await live_basis(
                            session, key["tenant_id"], key["scope_id"], [COMPETITOR_OPERATION]
                        )
                        prompt_ids = [int(row.id) for row in basis["prompts"]]
                        snapshots = list(await session.scalars(select(GeoAnswerSnapshot).where(
                            GeoAnswerSnapshot.tenant_id == key["tenant_id"],
                            GeoAnswerSnapshot.prompt_id.in_(prompt_ids),
                        ).order_by(GeoAnswerSnapshot.captured_at.desc(), GeoAnswerSnapshot.id.desc())
                          .limit(500).execution_options(populate_existing=True)))
                        questions = {int(row.id): row.question for row in basis["prompts"]}
                        competitor = alias.canonical_name or alias.alias_name
                        trace = build_competitor_trace(
                            competitor=competitor, rows=snapshots, questions=questions,
                        )
                        report = build_competitor_report_markdown(
                            competitor=competitor, trace=trace,
                        )
                        child = GeoAsyncJob(
                            tenant_id=key["tenant_id"], kind="automation_competitor_report",
                            status="succeeded", ref_type="competitor_alias", ref_id=alias.id,
                            request_meta={"request_id": token["request_id"],
                                          "automation_run_id": token["run_id"]},
                            result_meta={"schema": 1, "persisted": False, "report": report},
                            created_by=token["owner_user_id"], started_at=datetime.utcnow(),
                            finished_at=datetime.utcnow(),
                        )
                        session.add(child)
                        await session.flush()
                        await _bind_child_job(session, token, int(child.id))
                        await control.settle_step(
                            session, token, status="succeeded", fee_state="not_called",
                            evidence_refs=(f"geo_async_job:{child.id}",),
                            result_links=(f"/api/v1/geo/content/async-jobs/{child.id}?tenant_id={key['tenant_id']}",),
                        )
                        competitor_job_id = int(child.id)
                    elif token.get("operation") == MASTER_OPERATION:
                        from app.models import GeoArticleVersion, GeoContentTask
                        target = token["target"]
                        task = await session.scalar(select(GeoContentTask).where(
                            GeoContentTask.id == target["object_id"],
                            GeoContentTask.tenant_id == key["tenant_id"],
                            GeoContentTask.status.notin_(("archived", "cancelled")),
                        ).with_for_update().execution_options(populate_existing=True))
                        existing = await session.scalar(select(GeoArticleVersion.id).where(
                            GeoArticleVersion.task_id == target["object_id"]
                        ).limit(1))
                        if task is None or existing is not None:
                            raise control.problem("automation_target_changed", "母稿目标已变化，请刷新")
                        child = GeoAsyncJob(
                            tenant_id=key["tenant_id"], kind=async_jobs.KIND_GENERATE,
                            status="pending", ref_type="content_task", ref_id=task.id,
                            request_meta={"automation_token": token,
                                          "request_id": token["request_id"]},
                            created_by=token["owner_user_id"],
                        )
                        session.add(child)
                        await session.flush()
                        await _bind_child_job(session, token, int(child.id))
                        master_job_id = int(child.id)
                    elif token.get("operation") == VARIANT_OPERATION:
                        from app.models import GeoContentTask
                        target = token["target"]
                        task = await session.scalar(select(GeoContentTask).where(
                            GeoContentTask.id == target["object_id"],
                            GeoContentTask.tenant_id == key["tenant_id"],
                            GeoContentTask.status.notin_(("archived", "cancelled")),
                        ).with_for_update().execution_options(populate_existing=True))
                        if task is None or not target.get("variant"):
                            raise control.problem("automation_target_changed", "渠道稿目标已变化，请刷新")
                        child = GeoAsyncJob(
                            tenant_id=key["tenant_id"], kind=async_jobs.KIND_VARIANTS,
                            status="pending", ref_type="content_task", ref_id=task.id,
                            request_meta={"automation_token": token,
                                          "request_id": token["request_id"],
                                          "channels": [target["variant"]],
                                          "use_llm": False},
                            created_by=token["owner_user_id"],
                        )
                        session.add(child)
                        await session.flush()
                        await _bind_child_job(session, token, int(child.id))
                        variant_job_id = int(child.id)
                    elif token.get("operation") == ONSITE_OPERATION:
                        row = await session.get(
                            GeoActionTicket, token["task_id"], with_for_update=True,
                            populate_existing=True,
                        )
                        value = ((row.progress or {}).get("onsite") or {}) if row is not None else {}
                        if (row is None or int(row.id) != int(token["task_id"])
                                or row.tenant_id != key["tenant_id"]
                                or not (row.advice_code or "").startswith(PREFIX)
                                or value.get("project_id") != key["scope_id"]):
                            raise control.problem(
                                "automation_task_not_found", "站内任务已不属于当前项目", 404
                            )
                        blocker = _automatic_initial_blocker(value)
                        if blocker:
                            raise control.problem(*blocker)
                        job = await enqueue_proposal_locked(
                            session, project=project, row=row,
                            actor_user_id=token["owner_user_id"], request_id=token["request_id"],
                            expected_revision=int(value.get("revision") or 0), mode="initial",
                            automation_token=token,
                        )
                        await _bind_child_job(session, token, int(job.id))
                    elif token.get("operation") == PERIODIC_OPERATION:
                        # The workflow helper performs its own locked write
                        # after this shared claim transaction is committed.
                        pass
                    elif token.get("operation") == OUTCOME_OPERATION:
                        # The outcome helper reopens a fresh transaction and
                        # revalidates this exact target before any ticket write.
                        pass
                    elif token.get("operation") == PUBLICATION_OPERATION:
                        pass
                    else:
                        raise control.problem("automation_operation_not_supported", "所选操作尚未接入执行")
                else:
                    row = await session.get(
                        GeoActionTicket, token["task_id"], with_for_update=True, populate_existing=True
                    )
                    value = ((row.progress or {}).get("onsite") or {}) if row is not None else {}
                    if (row is None or int(row.id) != int(token["task_id"])
                            or row.tenant_id != key["tenant_id"]
                            or not (row.advice_code or "").startswith(PREFIX)
                            or value.get("project_id") != key["scope_id"]):
                        raise control.problem(
                            "automation_task_not_found", "站内任务已不属于当前项目", 404
                        )
                    blocker = _automatic_initial_blocker(value)
                    if blocker:
                        raise control.problem(*blocker)
                    job = await enqueue_proposal_locked(
                        session, project=project, row=row,
                        actor_user_id=token["owner_user_id"], request_id=token["request_id"],
                        expected_revision=int(value.get("revision") or 0), mode="initial",
                        automation_token=token,
                    )
                    await _bind_child_job(session, token, int(job.id))
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, dict) else {}
                code = detail.get("code") or "automation_preflight_blocked"
                await control.settle_step(
                    session, token, status="blocked", error_code=code,
                    fee_state="not_called",
                )
                continue_after_block = True
            else:
                if token.get("operation") == VISIBILITY_OPERATION:
                    job_id = ("patrol", patrol_id, token)
                elif token.get("operation") == PERIODIC_OPERATION:
                    job_id = ("periodic", None, token)
                elif token.get("operation") == OUTCOME_OPERATION:
                    job_id = ("outcome", None, token)
                elif token.get("operation") == PUBLICATION_OPERATION:
                    job_id = ("publication", None, token)
                elif token.get("operation") == BRIEF_OPERATION:
                    job_id = ("continue", brief_job_id, token)
                elif token.get("operation") == COMPETITOR_OPERATION:
                    job_id = ("continue", competitor_job_id, token)
                elif token.get("operation") == MASTER_OPERATION:
                    job_id = master_job_id
                elif token.get("operation") == VARIANT_OPERATION:
                    job_id = variant_job_id
                else:
                    job_id = int(job.id)
            await session.commit()
    except SQLAlchemyError:
        raise
    except Exception:
        # Database, append-only event or commit failure is an unknown write
        # outcome.  Never reuse an old claim token or recurse into a paid path.
        return
    if isinstance(job_id, tuple) and job_id[0] == "patrol":
        await _finish_patrol_step(key, run_id, job_id[2], job_id[1])
    elif isinstance(job_id, tuple) and job_id[0] == "periodic":
        await _finish_periodic_step(key, run_id, job_id[2])
    elif isinstance(job_id, tuple) and job_id[0] == "outcome":
        await _finish_outcome_step(key, run_id, job_id[2])
    elif isinstance(job_id, tuple) and job_id[0] == "publication":
        await _finish_publication_step(key, run_id, job_id[2])
    elif isinstance(job_id, tuple) and job_id[0] == "continue":
        await run_automation(key, run_id)
    elif job_id is not None:
        await async_jobs.run_job_in_background(job_id, key["tenant_id"])
    elif continue_after_block:
        await run_automation(key, run_id)


async def recover_automation_runs(limit: int = 20) -> int:
    """Restart only undispatched shared steps; paid/uncertain dispatches stay closed."""
    async with async_session_factory() as session:
        if not await control.schema_ready(session):
            return 0
        rows = list((await session.execute(text("""
            SELECT p.module,p.tenant_id,p.scope_id,p.current_run_id
            FROM automation_projects p
            JOIN automation_project_runs r ON r.id=p.current_run_id
              AND r.module=p.module AND r.tenant_id=p.tenant_id AND r.scope_id=p.scope_id
            WHERE p.module='geo' AND p.state='active' AND p.current_run_id IS NOT NULL
              AND NOT r.stop_requested
              AND EXISTS (SELECT 1 FROM jsonb_array_elements(r.steps) step
                          WHERE step->>'status'='pending')
              AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(r.steps) step
                              WHERE step->>'status'='running')
            ORDER BY p.updated_at,p.scope_id LIMIT :limit
        """), {"limit": max(1, min(int(limit), 50))})).mappings())
        due = list((await session.execute(text("""
            SELECT module,tenant_id,scope_id
            FROM automation_projects
            WHERE module='geo' AND state='idle' AND cycle_enabled
              AND next_due_at IS NOT NULL AND next_due_at <= CURRENT_TIMESTAMP
            ORDER BY next_due_at,scope_id LIMIT :limit
        """), {"limit": max(1, min(int(limit), 50))})).mappings())
    started = []
    for item in due:
        key = control.scope("geo", int(item["tenant_id"]), int(item["scope_id"]))
        try:
            async with async_session_factory() as session:
                project = await control.read_project(session, key, lock=True)
                if (not project or project["state"] != "idle" or not project["cycle_enabled"]
                        or project["next_due_at"] is None):
                    continue
                await ensure_geo_entitlement(
                    session, key["tenant_id"], allow_demo_read=False, lock_binding=True
                )
                geo_project = await session.get(
                    GeoProject, key["scope_id"], with_for_update=True, populate_existing=True
                )
                owner = int(project["owner_user_id"])
                if (geo_project is None or geo_project.tenant_id != key["tenant_id"]
                        or geo_project.status != "active"
                        or plan_for(geo_project).get("advisor_user_id") != owner
                        or not await advisor_available(session, key["tenant_id"], owner, lock=True)):
                    continue
                new_run = await control.start_run(
                    session, key, project, actor_kind="system", actor_id=None
                )
                await session.commit()
                started.append((key, str(new_run)))
        except HTTPException:
            continue
    await asyncio.gather(*(
        run_automation(control.scope("geo", int(row["tenant_id"]), int(row["scope_id"])),
                       str(row["current_run_id"]))
        for row in rows
    ), *(run_automation(key, run_id) for key, run_id in started))
    return len(rows) + len(started)
