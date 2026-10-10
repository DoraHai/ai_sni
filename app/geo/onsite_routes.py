"""Project-scoped website delivery, independent of article publication and AI visibility."""
import asyncio
import hashlib
import ipaddress
import json
from datetime import date, datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, PositiveInt
from sqlalchemy import and_, case, func, or_, select

from app import onsite_workflow as work
from app.database import get_session
from app.models import GeoProject, GeoActionTicket, GeoAsyncJob, GeoFact, GeoPrompt, Tenant
from app.security.auth import require_scoped_auth
from app.geo.project_scope import binding, project_scope, prompt_ids_for_businesses
from app.geo.project_workflows import PLAN_KEY, plan_for, advisor_available
from app.geo.tenant_scope import ensure_geo_entitlement
from app.geo.audit import safe_fetch, GeoAuditError
from app.geo.content.ai_settings import resolve_llm_credentials
from app.geo.content import async_jobs
from app.geo import onsite_ai, onsite_jobs

router = APIRouter()
PREFIX = "onsite:v1:"
MAX_PUBLIC_FACTS = 30
MAX_PRIORITY_QUESTIONS = 50
ONSITE_PROTOCOL = "durable-v1"
_PUBLIC_RUN_STATES = frozenset({
    "queued", "running", "ready", "failed", "unknown", "stale", "cancelled",
})
_PUBLIC_ERROR_CATEGORIES = frozenset({
    "pre_execution", "admission_denied", "admission_unavailable",
    "metering_finalize_unknown", "authentication", "rate_limit",
    "invalid_request", "provider_unavailable", "model_not_found", "timeout",
    "network", "invalid_response", "unknown", "result_validation",
    "save_unknown", "interrupted", "queue_timeout",
})
_PUBLIC_ERROR_CODES = frozenset({
    "api_concurrency_limit", "api_budget_exhausted", "api_charge_unresolved",
    "api_provider_disabled", "api_budget_quote_unavailable", "model_not_found",
})

class Create(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    tenant_id: PositiveInt
    project_id: PositiveInt
    request_id: UUID
    work_type: Literal["startup", "monthly", "remediation"]
    month: str | None = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    owner_name: str = Field(min_length=1, max_length=100)

class Update(work.Change):
    tenant_id: PositiveInt
    project_id: PositiveInt


class AiProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    tenant_id: PositiveInt
    project_id: PositiveInt
    expected_revision: int = Field(ge=1)
    request_id: UUID
    mode: Literal["initial", "revise"]

async def can_operate(session, ctx, project, *, lock_advisor=False):
    return bool(ctx.user_id and ctx.can_edit("geo.assets") and ctx.can_edit("geo.content")
        and project.status == "active" and plan_for(project).get("advisor_user_id") == ctx.user_id
        and await advisor_available(
            session, project.tenant_id, ctx.user_id, lock=lock_advisor))

async def scope(session, ctx, tenant_id, project_id, write=False):
    ctx.ensure_tenant(tenant_id)
    if not (ctx.can_view("geo.assets") and ctx.can_view("geo.content")):
        raise HTTPException(403, "需要官网资产与内容查看权限")
    await ensure_geo_entitlement(session, tenant_id, allow_demo_read=not write, lock_binding=write)
    project, _ = await project_scope(session, tenant_id, project_id)
    if write:
        project = await session.get(GeoProject, project_id, with_for_update=True, populate_existing=True)
        if not await can_operate(session, ctx, project):
            raise HTTPException(403, "需要当前项目有效顾问分配及资产、内容编辑权限；请先配置项目服务计划")
    return project

def _next_action(value: dict) -> str:
    stored_run = value.get("ai_run") if isinstance(value.get("ai_run"), dict) else None
    if stored_run and stored_run.get("state") == "queued":
        return "AI 方案已入队，可等待或由发起顾问取消"
    if stored_run and stored_run.get("state") == "running":
        return "AI 方案执行中，可等待或由发起顾问请求取消"
    run = onsite_ai.projected_ai_run(value)
    if run and run.get("state") in {"failed", "unknown", "stale"}:
        return "人工核对 AI 调用状态后决定是否重新生成"
    return {
        "draft": "完善方案并提交人工审核",
        "review": "人工核对事实、范围与预期内容",
        "implementation": "按审核方案人工实施官网修改",
        "recheck": "对真实页面执行复检",
        "acceptance": "人工完成最终验收",
        "done": "已完成",
        "cancelled": "已取消",
    }.get(value.get("phase"), "人工核对任务状态")


def _blocker(value: dict, project: GeoProject) -> str | None:
    run = onsite_ai.projected_ai_run(value)
    if run and run.get("state") in {"failed", "unknown", "stale"}:
        return run.get("error") or "AI 方案生成需要人工处理"
    settings = project.project_settings if isinstance(project.project_settings, dict) else {}
    return settings.get("geo_workflow_blocker")


def public(row, project, can_write, *, provider_ready=False, provider_reason=None, tenant_name=None):
    value = dict(row.progress["onsite"])
    stored_run = value.get("ai_run") if isinstance(value.get("ai_run"), dict) else {}
    active_ai = stored_run.get("state") in {"queued", "running"}
    # Durable jobs are reconciled by the background owner/recovery path.  Do
    # not invent a read-time stale state that disagrees with request_run.
    projected = dict(stored_run) if stored_run.get("job_id") else onsite_ai.projected_ai_run(value)
    if projected:
        projected.pop("request_hash", None)
        value["ai_run"] = projected
    proposal = onsite_ai.public_ai_proposal(value.get("ai_proposal"))
    if proposal is not None:
        value["ai_proposal"] = proposal
    allowed_actions = [] if active_ai else work.allowed_actions(value, can_write)
    capabilities = onsite_ai.capabilities(provider_ready=provider_ready, can_write=can_write,
                                            phase=value["phase"], reason=provider_reason)
    if active_ai:
        capabilities["ai_planning"] = {
            **capabilities["ai_planning"], "can_generate": False,
            "reason": "AI 方案正在排队或执行",
        }
    return dict(id=row.id, module="geo", tenant_id=row.tenant_id, scope_id=project.id,
        title=row.title, workflow=value, allowed_actions=allowed_actions,
        completion_evidence=dict(acceptance=value.get("acceptance"), recheck=value.get("recheck")) if value["phase"] == "done" else None,
        scope_name=project.name, tenant_name=tenant_name,
        next_action=_next_action(value), blocker=_blocker(value, project),
        capabilities=capabilities)


async def _provider_status(session, tenant_id: int) -> tuple[bool, str | None]:
    credentials = await resolve_llm_credentials(session, tenant_id) or {}
    try:
        selected = onsite_ai.select_planning_credentials(credentials)
    except HTTPException as exc:
        return False, str(exc.detail)
    return (True, None) if selected.get("api_key") else (False, None)


async def _public(session, row, project, can_write):
    tenant = await session.get(Tenant, row.tenant_id)
    provider_ready, provider_reason = await _provider_status(session, row.tenant_id)
    return public(row, project, can_write,
                  provider_ready=provider_ready, provider_reason=provider_reason,
                  tenant_name=tenant.name if tenant else None)

@router.get("/workbench/onsite-tasks")
async def list_tasks(tenant_id: PositiveInt, project_id: PositiveInt, before_id: PositiveInt | None = None,
                     session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    project = await scope(session, ctx, tenant_id, project_id)
    query = select(GeoActionTicket).where(GeoActionTicket.tenant_id == tenant_id,
        GeoActionTicket.advice_code.startswith(PREFIX),
        GeoActionTicket.progress["onsite"]["project_id"].as_integer() == project_id)
    if before_id:
        query = query.where(GeoActionTicket.id < before_id)
    rows = list(await session.scalars(query.order_by(GeoActionTicket.id.desc()).limit(21)))
    permitted = await can_operate(session, ctx, project)
    tenant = await session.get(Tenant, tenant_id)
    provider_ready, provider_reason = await _provider_status(session, tenant_id)
    return dict(module="geo", tenant_id=tenant_id, scope_id=project_id, can_create=permitted,
        items=[public(r, project, permitted, provider_ready=provider_ready,
                      provider_reason=provider_reason,
                      tenant_name=tenant.name if tenant else None) for r in rows[:20]],
        next_before_id=rows[19].id if len(rows) > 20 else None)


@router.get("/workbench/advisor-tasks")
async def advisor_tasks(tenant_id: PositiveInt | None = None, before_id: PositiveInt | None = None,
                        limit: int = Query(20, ge=1, le=50), session=Depends(get_session),
                        ctx=Depends(require_scoped_auth)):
    """Return only onsite tasks assigned to the authenticated real advisor."""
    if not ctx.user_id or not (ctx.can_edit("geo.assets") and ctx.can_edit("geo.content")):
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
    candidates = list(await session.scalars(query.order_by(GeoProject.id)))
    projects: dict[int, GeoProject] = {}
    for project in candidates:
        try:
            await ensure_geo_entitlement(session, project.tenant_id, allow_demo_read=False, lock_binding=False)
            await project_scope(session, project.tenant_id, project.id)
            if await advisor_available(session, project.tenant_id, ctx.user_id):
                projects[project.id] = project
        except HTTPException:
            continue
    if not projects:
        return {"schema": 1, "module": "geo", "items": [], "next_before_id": None}
    stmt = select(GeoActionTicket).where(
        GeoActionTicket.advice_code.startswith(PREFIX),
        or_(*[
            and_(GeoActionTicket.tenant_id == project.tenant_id,
                 GeoActionTicket.progress["onsite"]["project_id"].as_integer() == project.id)
            for project in projects.values()
        ]),
    )
    if before_id is not None:
        stmt = stmt.where(GeoActionTicket.id < before_id)
    rows = list(await session.scalars(stmt.order_by(GeoActionTicket.id.desc()).limit(limit + 1)))
    items = []
    tenant_cache: dict[int, tuple[str | None, bool, str | None]] = {}
    for row in rows[:limit]:
        project = projects.get(int(row.progress["onsite"]["project_id"]))
        if project is None or row.tenant_id != project.tenant_id:
            continue
        if row.tenant_id not in tenant_cache:
            tenant = await session.get(Tenant, row.tenant_id)
            provider_ready, provider_reason = await _provider_status(session, row.tenant_id)
            tenant_cache[row.tenant_id] = (
                tenant.name if tenant else None, provider_ready, provider_reason)
        tenant_name, provider_ready, provider_reason = tenant_cache[row.tenant_id]
        items.append(public(row, project, True, provider_ready=provider_ready,
                            provider_reason=provider_reason,
                            tenant_name=tenant_name))
    return {"schema": 1, "module": "geo", "items": items,
            "next_before_id": rows[limit - 1].id if len(rows) > limit else None}


def _verified_fact(row: GeoFact) -> bool:
    if row.status != "active" or row.trust_level != "verified" or not row.source_url:
        return False
    if row.expires_at is not None and row.expires_at < date.today():
        return False
    try:
        parsed = urlsplit(row.source_url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return False
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".local", ".internal")):
        return False
    try:
        if not ipaddress.ip_address(host).is_global:
            return False
    except ValueError:
        pass
    meta = row.meta if isinstance(row.meta, dict) else {}
    verification = meta.get("verification") if isinstance(meta.get("verification"), dict) else {}
    return bool(onsite_ai.public_use_authorized(meta)
                and (verification.get("verified_at") or meta.get("verified_at"))
                and (verification.get("excerpt") or meta.get("source_excerpt"))
                and (verification.get("excerpt_locator") or meta.get("excerpt_locator")))


async def _proposal_snapshot(session, project: GeoProject, row: GeoActionTicket) -> dict[str, Any]:
    """Freeze public, project-approved inputs; never include private fact metadata."""
    _, business_ids = await project_scope(session, project.tenant_id, project.id)
    plan = plan_for(project)
    current_prompt_ids = set(await prompt_ids_for_businesses(session, project.tenant_id, business_ids))
    selected_ids = [int(value) for value in plan.get("prompt_ids", []) if int(value) in current_prompt_ids]
    if len(selected_ids) > MAX_PRIORITY_QUESTIONS:
        raise HTTPException(409, f"当前项目重点问题超过 {MAX_PRIORITY_QUESTIONS} 条，请缩小服务计划范围")
    prompts = list(await session.scalars(select(GeoPrompt).where(
        GeoPrompt.tenant_id == project.tenant_id,
        GeoPrompt.id.in_(selected_ids or [-1]),
        GeoPrompt.status == "active",
        GeoPrompt.is_brand_probe.is_(False),
    ).order_by(GeoPrompt.id)))
    facts = list(await session.scalars(select(GeoFact).where(
        GeoFact.tenant_id == project.tenant_id,
        GeoFact.status == "active",
        or_(GeoFact.business_id.is_(None), GeoFact.business_id.in_(business_ids or [-1])),
    ).order_by(GeoFact.id)))
    approved_facts = [onsite_ai.public_source(fact, statement_publicly_authorized=True)
                      for fact in facts if _verified_fact(fact)]
    if len(approved_facts) > MAX_PUBLIC_FACTS:
        raise HTTPException(409, f"当前项目获准公开事实超过 {MAX_PUBLIC_FACTS} 条，请缩小事实范围")
    workflow = row.progress["onsite"]
    payload = {
        "project": {
            "id": project.id,
            "name": project.name,
            "brand_name": project.brand_name,
            "domain": project.canonical_domain,
            "scope_revision": binding(project)["revision"],
            "plan_revision": int(plan.get("revision") or 0),
        },
        "questions": [{"id": prompt.id, "question": prompt.question} for prompt in prompts],
        "facts": approved_facts,
        "items": [dict(item) for item in workflow["items"]],
        "workflow_revision": int(workflow["revision"]),
    }
    payload["source_hash"] = onsite_ai.source_hash(payload)
    return payload


def _request_run(job: GeoAsyncJob, value: dict | None = None, *, can_cancel: bool = False) -> dict[str, Any]:
    meta = job.request_meta if isinstance(job.request_meta, dict) else {}
    result = job.result_meta if isinstance(job.result_meta, dict) else {}
    run = dict((value or {}).get("ai_run") or {})
    current = run.get("request_id") == meta.get("request_id") and int(run.get("job_id") or 0) == int(job.id)
    terminal = job.status in {"succeeded", "failed", "cancelled"}
    raw_state = result.get("public_state") if terminal else (run.get("state") if current else None)
    error = result.get("message") if terminal else (run.get("error") if current else None)
    diagnostics = result if terminal else (run if current else {})
    state = raw_state if raw_state in _PUBLIC_RUN_STATES else {
        "pending":"queued", "running":"running", "succeeded":"ready",
        "cancelled":"cancelled", "failed":"failed",
    }.get(job.status, "failed")
    category = diagnostics.get("error_category")
    code = diagnostics.get("error_code")
    status = diagnostics.get("http_status")
    return {"request_id": str(meta.get("request_id") or ""), "job_id": int(job.id),
        "state": state, "cancel_requested": bool(meta.get("cancel_requested")),
        "can_cancel": bool(can_cancel and state in {"queued", "running"}), "error": error,
        "error_category": category if category in _PUBLIC_ERROR_CATEGORIES else None,
        "error_code": code if code in _PUBLIC_ERROR_CODES else None,
        "http_status": status if isinstance(status, int) and not isinstance(status, bool)
        and 100 <= status <= 599 else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "poll_url": f"/api/v1/geo/workbench/onsite-tasks/{job.ref_id}/ai-requests/{meta.get('request_id')}"}


async def _task_with_request(session, row, project, can_write, job, *, actor_user_id=None):
    payload = await _public(session, row, project, can_write)
    payload["request_run"] = _request_run(
        job, row.progress["onsite"],
        can_cancel=bool(can_write and actor_user_id is not None
                        and int(job.created_by or 0) == int(actor_user_id)),
    )
    return payload


async def _request_job(session, *, tenant_id: int, task_id: int, request_id: str,
                       lock: bool = False):
    query = select(GeoAsyncJob).where(
        GeoAsyncJob.tenant_id == tenant_id,
        GeoAsyncJob.kind == async_jobs.KIND_ONSITE_PROPOSAL,
        GeoAsyncJob.ref_type == "onsite_task", GeoAsyncJob.ref_id == task_id,
        GeoAsyncJob.request_meta["request_id"].as_string() == request_id,
    ).order_by(GeoAsyncJob.id.desc()).limit(1)
    return await session.scalar(query.with_for_update() if lock else query)


@router.post("/workbench/onsite-tasks/{task_id}/ai-proposal", status_code=202)
async def ai_proposal(task_id: PositiveInt, req: AiProposal,
                      session=Depends(get_session), ctx=Depends(require_scoped_auth),
                      background_tasks: BackgroundTasks = None, response: Response = None,
                      protocol: Annotated[
                          str | None, Header(alias="X-Snipers-Onsite-Protocol")
                      ] = None):
    """Durably enqueue one proposal request and return without waiting for AI."""
    if protocol != ONSITE_PROTOCOL:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "工作台版本过旧，请刷新页面后重试",
                "code": "onsite_client_upgrade_required",
            },
            headers={"Cache-Control": "no-store"},
        )
    if ctx.user_id is None:
        raise HTTPException(403, "异步 AI 方案必须由实名顾问发起")
    project = await scope(session, ctx, req.tenant_id, req.project_id, True)
    row = await session.get(GeoActionTicket, task_id, with_for_update=True, populate_existing=True)
    if (not row or row.tenant_id != req.tenant_id or not (row.advice_code or "").startswith(PREFIX)
            or (row.progress or {}).get("onsite", {}).get("project_id") != project.id):
        raise HTTPException(404, "当前项目的站内任务不存在")
    value = dict(row.progress["onsite"])
    request_id = str(req.request_id)
    digest = onsite_ai.request_hash(task_id=task_id, tenant_id=req.tenant_id,
        project_id=req.project_id, expected_revision=req.expected_revision, mode=req.mode,
        actor_user_id=ctx.user_id)
    existing = value.get("ai_run") if isinstance(value.get("ai_run"), dict) else None
    if existing and existing.get("request_id") == request_id:
        if existing.get("request_hash") != digest:
            raise HTTPException(409, "请求编号已用于不同的 AI 方案参数")
        job = await _request_job(session, tenant_id=req.tenant_id, task_id=task_id, request_id=request_id)
        if job is None:
            raise HTTPException(409, "历史 AI 请求缺少持久化作业记录，请人工核对")
        if response is not None and _request_run(job, value)["state"] not in {"queued", "running"}:
            response.status_code = 200
        return await _task_with_request(session, row, project, True, job,
                                        actor_user_id=ctx.user_id)
    if existing and existing.get("state") in {"queued", "running"}:
        raise HTTPException(409, "当前任务已有 AI 方案排队或执行中")
    if value["revision"] != req.expected_revision:
        raise HTTPException(409, "任务版本已变化，请重新读取核对后操作")
    if "save_proposal" not in work.allowed_actions(value, True):
        raise HTTPException(409, "当前任务状态不能生成 AI 方案")
    if (req.mode == "initial") != (value["phase"] == "draft"):
        raise HTTPException(409, "draft 阶段使用 initial，其余可写阶段使用 revise")
    if len(value.get("history") or []) >= 100:
        raise HTTPException(409, "任务历史达到上限，请保留记录并建立后续任务")
    credentials = onsite_ai.select_planning_credentials(await resolve_llm_credentials(session, req.tenant_id) or {})
    if not credentials.get("api_key"):
        raise HTTPException(409, "平台 AI 供应商尚未配置")
    snapshot = await _proposal_snapshot(session, project, row)
    onsite_ai.planning_preflight(snapshot)
    project.project_settings = onsite_ai.reserve_daily(project.project_settings, request_id, request_digest=digest)
    job = GeoAsyncJob(tenant_id=req.tenant_id, kind=async_jobs.KIND_ONSITE_PROPOSAL,
        status="pending", ref_type="onsite_task", ref_id=task_id, created_by=ctx.user_id,
        request_meta={"schema":1, "request_id":request_id, "request_hash":digest,
            "task_id":int(task_id), "project_id":int(req.project_id), "actor_user_id":int(ctx.user_id),
            "expected_revision":int(req.expected_revision), "mode":req.mode,
            "source_hash":snapshot["source_hash"], "execution_protocol":async_jobs.JOB_EXECUTION_PROTOCOL})
    job.request_meta = {
        **job.request_meta,
        "provider_route": onsite_ai.planning_route(credentials),
    }
    session.add(job)
    await session.flush()
    value["ai_run"] = {"request_id":request_id, "request_hash":digest, "job_id":int(job.id),
        "state":"queued", "mode":req.mode, "source_revision":req.expected_revision,
        "source_hash":snapshot["source_hash"], "actor_user_id":ctx.user_id,
        "queued_at":onsite_ai.now_iso()}
    row.progress = {**(row.progress or {}), "onsite":value}
    row.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(job); await session.refresh(row)
    if background_tasks is not None:
        background_tasks.add_task(async_jobs.run_job_in_background, job.id, job.tenant_id)
    return await _task_with_request(session, row, project, True, job,
                                    actor_user_id=ctx.user_id)


@router.get("/workbench/onsite-ai/health")
async def onsite_ai_health(
    response: Response,
    session=Depends(get_session),
    ctx=Depends(require_scoped_auth),
):
    """Read-only process evidence and aggregate queue state for global operations."""
    if not ctx.is_superadmin or ctx.tenant_id is not None:
        raise HTTPException(403, "仅全局超级管理员可查看站内 AI 健康状态")
    unknown = and_(
        GeoAsyncJob.status == "failed",
        GeoAsyncJob.result_meta["public_state"].as_string() == "unknown",
    )
    queue = (await session.execute(select(
        func.count().filter(GeoAsyncJob.status == "pending").label("queued"),
        func.count().filter(GeoAsyncJob.status == "running").label("running"),
        func.count().filter(unknown).label("unknown"),
        func.min(case((GeoAsyncJob.status == "pending", GeoAsyncJob.created_at))).label(
            "oldest_queued_at"
        ),
        func.min(case((GeoAsyncJob.status == "running", GeoAsyncJob.started_at))).label(
            "oldest_running_at"
        ),
    ).where(GeoAsyncJob.kind == async_jobs.KIND_ONSITE_PROPOSAL))).one()
    worker = onsite_jobs.pending_worker_status()
    response.headers["Cache-Control"] = "no-store"
    return {
        "schema": 1,
        "module": "geo",
        "observed_at": onsite_ai.now_iso(),
        "worker": {
            "scope": "this_process",
            "enabled": bool(worker.get("enabled")),
            "state": worker.get("state") if worker.get("state") in {
                "active", "degraded", "stopped", "disabled", "unverified",
            } else "unverified",
            "verified": bool(worker.get("verified")),
            "evidence": worker.get("evidence") if worker.get("evidence") in {
                "tick", "error", "stopped", "disabled", "none",
            } else "none",
            "last_tick_at": worker.get("last_tick_at"),
            "last_attempted": int(worker.get("last_attempted") or 0),
            "last_completed": int(worker.get("last_completed") or 0),
            "last_error": worker.get("last_error"),
        },
        "queue": {
            "queued": int(queue.queued or 0),
            "running": int(queue.running or 0),
            "unknown": int(queue.unknown or 0),
            "oldest_queued_at": queue.oldest_queued_at.isoformat()
            if queue.oldest_queued_at else None,
            "oldest_running_at": queue.oldest_running_at.isoformat()
            if queue.oldest_running_at else None,
        },
    }


@router.get("/workbench/onsite-tasks/{task_id}/ai-requests/{request_id}")
async def get_ai_request(task_id: PositiveInt, request_id: UUID, tenant_id: PositiveInt,
                         project_id: PositiveInt, session=Depends(get_session),
                         ctx=Depends(require_scoped_auth)):
    """Pure status read; never reconciles, initializes, retries or calls AI."""
    project = await scope(session, ctx, tenant_id, project_id)
    row = await session.get(GeoActionTicket, task_id)
    if (not row or row.tenant_id != tenant_id or not (row.advice_code or "").startswith(PREFIX)
            or (row.progress or {}).get("onsite", {}).get("project_id") != project.id):
        raise HTTPException(404, "当前项目的站内任务不存在")
    job = await _request_job(session, tenant_id=tenant_id, task_id=task_id,
                             request_id=str(request_id))
    if job is None:
        raise HTTPException(404, "AI 请求不存在")
    permitted = await can_operate(session, ctx, project)
    return await _task_with_request(session, row, project, permitted, job,
                                    actor_user_id=ctx.user_id)


@router.post("/workbench/onsite-tasks/{task_id}/ai-requests/{request_id}/cancel")
async def cancel_ai_request(task_id: PositiveInt, request_id: UUID, tenant_id: PositiveInt,
                            project_id: PositiveInt, session=Depends(get_session),
                            ctx=Depends(require_scoped_auth)):
    project = await scope(session, ctx, tenant_id, project_id, True)
    row = await session.get(GeoActionTicket, task_id, with_for_update=True, populate_existing=True)
    if (not row or row.tenant_id != tenant_id or not (row.advice_code or "").startswith(PREFIX)
            or (row.progress or {}).get("onsite", {}).get("project_id") != project.id):
        raise HTTPException(404, "当前项目的站内任务不存在")
    job = await _request_job(session, tenant_id=tenant_id, task_id=task_id,
                             request_id=str(request_id), lock=True)
    if job is None:
        raise HTTPException(404, "AI 请求不存在")
    if int(job.created_by or 0) != int(ctx.user_id or 0):
        raise HTTPException(403, "只有发起该请求的当前顾问可以取消")
    await async_jobs.request_cancel(session, job)
    await session.refresh(row); await session.refresh(job)
    value = dict(row.progress["onsite"]); run = dict(value.get("ai_run") or {})
    if (run.get("request_id") == str(request_id) and int(run.get("job_id") or 0) == int(job.id)
            and job.status == "cancelled"):
        run.update(state="cancelled", error="请求已取消", finished_at=onsite_ai.now_iso())
        value["ai_run"] = run; row.progress = {**(row.progress or {}), "onsite":value}
        row.updated_at = datetime.utcnow(); await session.commit(); await session.refresh(row)
    return await _task_with_request(session, row, project, True, job,
                                    actor_user_id=ctx.user_id)


@router.post("/workbench/onsite-tasks")
async def create(req: Create, session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    project = await scope(session, ctx, req.tenant_id, req.project_id, True)
    code = PREFIX + str(req.request_id)
    request_hash = hashlib.sha256(json.dumps(req.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
    existing = await session.scalar(select(GeoActionTicket).where(GeoActionTicket.tenant_id == req.tenant_id,
        GeoActionTicket.advice_code == code).limit(1))
    if existing:
        if existing.progress["onsite"]["project_id"] != project.id:
            raise HTTPException(409, "此请求编号已用于其他项目")
        if existing.progress["onsite"].get("request_hash") != request_hash:
            raise HTTPException(409, "请求编号已用于不同任务参数")
        return await _public(session, existing, project, True)
    domain = project.canonical_domain
    base = f"https://{domain}/"
    definitions = [
        ("structured_content", base, "按实体、产品、服务、适用范围、出处和更新时间组织官网内容，填写需要核对的完整内容片段。"),
        ("knowledge", base, "填写实际知识库页面地址与审核过的知识片段，维护事实来源、版本和适用范围。"),
        ("faq", base, "填写实际 FAQ 页地址与审核过的问答片段，问答需要在页面可见。"),
        ("schema", base, "填写实际页面地址与审核 JSON；标记必须对应页面可见内容，复检核对 JSON 子集。"),
        ("llms", base+"llms.txt", "填写审核过的文件片段及官网、知识库、FAQ 入口；文件需有 Markdown 主标题。"),
    ]
    items = [dict(id=kind, kind=kind, target_url=url, expected="", instruction=instruction)
             for kind, url, instruction in definitions]
    value = work.new_workflow("geo", req.work_type, req.month, domain, items, ctx.user_id, req.owner_name)
    value["project_id"] = project.id
    value["request_hash"] = request_hash
    row = GeoActionTicket(tenant_id=req.tenant_id, advice_code=code, title="GEO 官网与知识内容建设",
        priority="medium", status="todo", owner_name=req.owner_name,
        action="保存审核版本，网站实施后真实复检并人工验收。",
        acceptance_type="manual", acceptance_check="onsite.versioned_delivery",
        acceptance_desc="结构化官网、知识库、FAQ、Schema 与 llms.txt 的当前审核版本均已实施并复检；人工核对事实和质量。",
        created_by=ctx.user_id, progress={"onsite": value}, evidence=[])
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return await _public(session, row, project, True)

@router.post("/workbench/onsite-tasks/{task_id}/actions")
async def act(task_id: PositiveInt, req: Update, session=Depends(get_session), ctx=Depends(require_scoped_auth)):
    project = await scope(session, ctx, req.tenant_id, req.project_id, True)
    row = await session.get(GeoActionTicket, task_id, with_for_update=True, populate_existing=True)
    if (not row or row.tenant_id != req.tenant_id or not (row.advice_code or "").startswith(PREFIX)
            or (row.progress or {}).get("onsite", {}).get("project_id") != project.id):
        raise HTTPException(404, "当前项目的站内任务不存在")
    active_run = (row.progress or {}).get("onsite", {}).get("ai_run")
    if isinstance(active_run, dict) and active_run.get("state") in {"queued", "running"}:
        raise HTTPException(409, "AI 方案正在排队或执行，请先等待结果或取消请求")
    value = work.prepare_change(row.progress["onsite"], req, "geo", project.canonical_domain, ctx.user_id)
    if req.action == "save_proposal":
        # A human edit creates a new proposal revision. Old AI reasoning must not
        # be presented as support for content it did not produce.
        value.pop("ai_proposal", None)
    if req.action == "recheck":
        project.project_settings = work.reserve_recheck(project.project_settings)
        async def fetch(url, kind):
            try:
                async with asyncio.timeout(20):
                    doc = await safe_fetch(url, allow_text=kind == "llms", allowed_hosts=work.host_scope(project.canonical_domain))
                return dict(body=doc.html, url=doc.final_url)
            except (GeoAuditError, TimeoutError) as exc:
                raise HTTPException(424, "页面读取失败") from exc
        value = await work.recheck(value, fetch)
    row.progress = {**(row.progress or {}), "onsite": value}
    row.status = {"done":"done", "cancelled":"blocked"}.get(value["phase"], "doing")
    row.owner_name = value["owner_name"]
    row.updated_at = datetime.utcnow()
    if value["phase"] == "done":
        row.last_verdict, row.last_verify_at, row.closed_at = "pass", datetime.utcnow(), datetime.utcnow()
        row.last_note = req.note
    await session.commit()
    await session.refresh(row)
    return await _public(session, row, project, True)

