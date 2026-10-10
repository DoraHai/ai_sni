"""Live advisor queue and idempotent, manually requested onsite AI proposals."""
import asyncio
import hashlib
from copy import deepcopy
from datetime import date, datetime
from typing import Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, PositiveInt
from sqlalchemy import and_, func, or_, select

from app import onsite_workflow as work, seo_onsite_ai as ai
from app.api import seo_onsite as onsite
from app.api_controls import ControlDenied
from app.api_metering import MeteringUnavailable
from app.models.module_workspace import SeoSite, TenantModule
from app.models.role import Role
from app.models.seo import SeoSiteAdvisorAssignment
from app.models.seo_cockpit import SeoTask
from app.models.tenant import Tenant
from app.models.user import User
from app.security.auth import AuthContext
from app.seo_demo_source import get_seo_session, require_seo_scoped_auth

router = APIRouter()


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: PositiveInt
    site_id: PositiveInt
    expected_revision: int = Field(ge=1)
    request_id: UUID
    mode: Literal["initial", "revise"]


async def fresh_context(session, ctx, *, lock=False):
    if ctx.user_id is None:
        raise ai.problem(403, "onsite_advisor_identity_required", "需要实名顾问账号")
    locks = {"with_for_update": {"read": True}} if lock else {}
    user = await session.get(User, ctx.user_id, populate_existing=True, **locks)
    role = await session.get(Role, user.role_id, populate_existing=True, **locks) if user else None
    if not user or not user.is_active or not role:
        raise ai.problem(403, "onsite_advisor_identity_expired", "顾问身份已失效")
    return AuthContext(user.id, user.username, role.name, user.tenant_id, dict(role.permissions or {}))


def advisor_query(user_id):
    # All ownership/assignment/entitlement filters precede the cursor and LIMIT.
    return (select(SeoTask, SeoSite, Tenant.name).join(SeoSite, and_(
        SeoTask.site_id == SeoSite.id, SeoTask.tenant_id == SeoSite.tenant_id))
        .join(Tenant, Tenant.id == SeoTask.tenant_id)
        .join(TenantModule, and_(TenantModule.id == SeoSite.tenant_module_id,
            TenantModule.tenant_id == SeoTask.tenant_id, TenantModule.module_code == "seo"))
        .join(SeoSiteAdvisorAssignment, and_(SeoSiteAdvisorAssignment.site_id == SeoSite.id,
            SeoSiteAdvisorAssignment.tenant_id == SeoTask.tenant_id,
            SeoSiteAdvisorAssignment.advisor_user_id == user_id, SeoSiteAdvisorAssignment.active.is_(True)))
        .join(User, User.id == SeoSiteAdvisorAssignment.advisor_user_id)
        .join(Role, Role.id == User.role_id)
        .where(SeoTask.action_type == onsite.ACTION_TYPE, SeoTask.module == "seo",
            SeoTask.params["onsite"]["schema"].astext == "1",
            User.is_active.is_(True), or_(User.tenant_id.is_(None), User.tenant_id == SeoTask.tenant_id),
            Role.permissions["seo.site"].astext == "edit", Role.permissions["seo.content"].astext == "edit",
            SeoSite.status == "active", TenantModule.status.in_(["active", "trial"]),
            or_(TenantModule.expires_at.is_(None), TenantModule.expires_at >= date.today())))


def summary(row, site, tenant_name, can_ai=True):
    result = onsite.public(row, True, site.site_settings, can_ai)
    w = result["workflow"]
    next_action = {"draft": "save_proposal", "review": "approve", "implementation": "implement",
                   "recheck": "recheck", "acceptance": "accept"}.get(w["phase"])
    blocker = None
    if w.get("ai_run", {}).get("state") in {"failed", "unknown", "stale"}:
        blocker = w["ai_run"].get("error")
    elif any(not i["expected"].strip() for i in w["items"]) and w["phase"] in {"draft", "review"}:
        blocker = {"code": "proposal_evidence_missing", "message": "请补齐预期内容和依据后人工审核"}
        next_action = "save_proposal"
    elif w["phase"] == "recheck" and w.get("recheck", {}).get("passed") is False:
        blocker = {"code": "page_recheck_failed", "message": "页面复检未通过，请核对实施或修订方案"}
    return {**result, "scope_name": site.name, "tenant_name": tenant_name,
            "next_action": next_action, "blocker": blocker}


@router.get("/workbench/advisor-tasks")
async def advisor_tasks(before_id: PositiveInt | None = None, limit: int = Query(20, ge=1, le=50),
                        tenant_id: PositiveInt | None = None,
                        session=Depends(get_seo_session), ctx=Depends(require_seo_scoped_auth)):
    fresh = await fresh_context(session, ctx)
    if tenant_id is not None:
        ctx.ensure_tenant(tenant_id)
        fresh.ensure_tenant(tenant_id)
    query = advisor_query(fresh.user_id)
    if ctx.tenant_id is not None:
        query = query.where(SeoTask.tenant_id == ctx.tenant_id)
    if tenant_id is not None:
        query = query.where(SeoTask.tenant_id == tenant_id)
    if before_id is not None:
        query = query.where(SeoTask.id < before_id)
    rows = list((await session.execute(query.order_by(SeoTask.id.desc()).limit(limit + 1)
                                      .execution_options(populate_existing=True))).all())
    return {"schema": 1, "module": "seo", "items": [summary(*r, can_ai=fresh.can_view("seo.keywords")) for r in rows[:limit]],
            "next_before_id": rows[limit - 1][0].id if len(rows) > limit else None}


async def authorized(session, ctx, req, site):
    ctx.ensure_tenant(req.tenant_id)
    fresh = await fresh_context(session, ctx, lock=True)
    fresh.ensure_tenant(req.tenant_id)
    if not site or site.tenant_id != req.tenant_id:
        raise ai.problem(404, "onsite_site_not_found", "当前客户的网站不存在")
    # Short-lived read locks prevent a permission change between the final
    # authorization read and commit. All are released before provider work.
    await session.get(TenantModule, site.tenant_module_id, with_for_update={"read": True}, populate_existing=True)
    await session.scalar(select(SeoSiteAdvisorAssignment).where(
        SeoSiteAdvisorAssignment.tenant_id == req.tenant_id, SeoSiteAdvisorAssignment.site_id == req.site_id,
        SeoSiteAdvisorAssignment.advisor_user_id == fresh.user_id).with_for_update(read=True)
        .execution_options(populate_existing=True))
    if not await onsite.can_operate(session, fresh, site) or not fresh.can_view("seo.keywords"):
        raise ai.problem(403, "onsite_advisor_forbidden", "需要有效顾问分配、网站和内容编辑及关键词查看权限")
    return fresh


def task_matches(row, req):
    if not row or (row.tenant_id, row.site_id, row.action_type) != (req.tenant_id, req.site_id, onsite.ACTION_TYPE):
        raise ai.problem(404, "onsite_task_not_found", "当前网站的站内任务不存在")


def public_run(run):
    return {k: v for k, v in run.items() if k in {
        "request_id", "state", "mode", "source_revision", "source_hash", "actor_user_id",
        "started_at", "finished_at", "error"}}


def save_run(row, run):
    key = run["request_id"]
    requests = {**(row.params.get("onsite_ai_requests") or {}), key: run}
    w = {**row.params["onsite"]}
    # A late result must not replace the state of a newer request.
    if not w.get("ai_run") or w["ai_run"]["request_id"] == key:
        w["ai_run"] = public_run(run)
    row.params = {**row.params, "onsite": w, "onsite_ai_requests": requests}
    row.updated_at = ai.now()


def failed_state(exc):
    cause = exc
    while cause.__cause__ is not None:
        cause = cause.__cause__
    if (isinstance(exc, (ControlDenied, MeteringUnavailable)) or isinstance(cause, httpx.HTTPStatusError)
            or isinstance(exc, HTTPException) and exc.status_code == 503):
        return "failed", {"code": "onsite_ai_provider_failed", "message": "调用未获准或供应商拒绝，请核对后再操作"}
    return "unknown", {"code": "onsite_ai_result_unknown", "message": "调用结果不明或返回无法核实；原请求不会自动重试"}


@router.post("/workbench/onsite-tasks/{task_id}/ai-proposal")
async def ai_proposal(task_id: PositiveInt, req: Request,
                      session=Depends(get_seo_session), ctx=Depends(require_seo_scoped_auth)):
    ctx.ensure_tenant(req.tenant_id)
    # Serialize the nonce across every task/site in this tenant, without a new
    # table or an unbounded site JSON index. The lock ends with the admission
    # commit; it is NEVER retained while waiting for the supplier.
    nonce_lock = int.from_bytes(hashlib.sha256(
        f"seo-onsite-ai:{req.tenant_id}:{req.request_id}".encode()).digest()[:8], "big", signed=True)
    await session.execute(select(func.pg_advisory_xact_lock(nonce_lock)))
    site = await session.get(SeoSite, req.site_id, with_for_update=True, populate_existing=True)
    fresh = await authorized(session, ctx, req, site)
    row = await session.get(SeoTask, task_id, with_for_update=True, populate_existing=True)
    task_matches(row, req)
    w = row.params["onsite"]
    if w["phase"] in {"done", "cancelled"} or row.status in {"done", "cancelled"}:
        raise ai.problem(409, "onsite_ai_task_closed", "任务已结束，不能生成或重放方案")
    key = str(req.request_id)
    other = await session.scalar(select(SeoTask.id).where(
        SeoTask.tenant_id == req.tenant_id, SeoTask.action_type == onsite.ACTION_TYPE, SeoTask.id != task_id,
        SeoTask.params["onsite_ai_requests"][key]["request_id"].astext == key).limit(1))
    if other is not None:
        raise ai.problem(409, "onsite_ai_request_conflict", "请求编号已用于其他站内任务，不会再次调用")
    request_hash = work.proposal_hash({**req.model_dump(mode="json"), "actor_user_id": fresh.user_id})
    requests = row.params.get("onsite_ai_requests") or {}
    prior = requests.get(key)
    if prior:
        if w.get("ai_run", {}).get("request_id") != key:
            raise ai.problem(409, "onsite_ai_request_superseded", "该请求已有后续方案，原请求不会再次调用")
        if prior["request_hash"] != request_hash:
            raise ai.problem(409, "onsite_ai_request_conflict", "请求编号已用于不同参数或操作人")
        if prior["state"] == "running" and (ai.now() - datetime.fromisoformat(prior["started_at"])).total_seconds() > ai.LEASE_SECONDS:
            prior = {**prior, "state": "unknown", "finished_at": ai.now().isoformat(),
                     "error": {"code": "onsite_ai_interrupted", "message": "原调用未完成核实，不会自动重试"}}
            save_run(row, prior)
            await session.commit()
        return {**onsite.public(row, True, site.site_settings), "replayed": True,
                "request_run": public_run(prior)}
    if w["revision"] != req.expected_revision:
        raise ai.problem(409, "onsite_ai_revision_changed", "任务版本已变化，请重新读取核对")
    if req.mode == "initial" and w["phase"] != "draft":
        raise ai.problem(409, "onsite_ai_mode_conflict", "已有方案请使用修订模式")
    if len(requests) >= ai.REQUEST_LIMIT or len(w["history"]) >= 100:
        raise ai.problem(409, "onsite_ai_task_limit", "任务调用或历史已达上限，请保留记录并建立后续任务")
    active = w.get("ai_run") or {}
    if active.get("state") == "running":
        if (ai.now() - datetime.fromisoformat(active["started_at"])).total_seconds() <= ai.LEASE_SECONDS:
            raise ai.problem(409, "onsite_ai_busy", "当前任务已有生成请求，请核对原请求")
        save_run(row, {**requests[active["request_id"]], "state": "unknown", "finished_at": ai.now().isoformat(),
            "error": {"code": "onsite_ai_interrupted", "message": "原调用未完成核实，不会自动重试"}})
    # Persist non-secret provider metadata along with quota and nonce. The API
    # projection only exposes the agreed public run fields, never credentials.
    _, base_url, model = ai.provider_route()
    provider_metadata = {"base_url": base_url, "model": model}
    facts = await ai.evidence(session, row, site)
    claim = {"request_id": key, "request_hash": request_hash, "state": "running", "mode": req.mode,
             "source_revision": w["revision"], "source_hash": work.proposal_hash(facts),
             "provider_metadata": provider_metadata,
             "actor_user_id": fresh.user_id, "started_at": ai.now().isoformat(), "finished_at": None}
    site.site_settings = ai.reserve(site.site_settings)
    row.params = {**row.params, "onsite": {**row.params["onsite"], "ai_run": {"request_id": key}}}
    save_run(row, claim)
    await session.commit()  # Durable nonce/quota BEFORE provider; release all row locks.
    raw, failure, cancelled = None, None, False
    try:
        async with asyncio.timeout(55):
            raw = await ai.generate(facts, req.tenant_id, req.site_id, fresh.user_id, task_id, key,
                                    expected_route=provider_metadata)
        items, reasons = ai.validate_result(raw, facts)
    except (Exception, asyncio.CancelledError) as exc:
        failure = failed_state(exc)
        cancelled = isinstance(exc, asyncio.CancelledError)
    # Re-read the actual identity, assignment, entitlement, source and task after the call.
    await session.rollback()
    session.expire_all()
    site = await session.get(SeoSite, req.site_id, with_for_update=True, populate_existing=True)
    row = await session.get(SeoTask, task_id, with_for_update=True, populate_existing=True)
    task_matches(row, req)
    run = deepcopy((row.params.get("onsite_ai_requests") or {}).get(key))
    if not run or run["state"] != "running":
        raise ai.problem(409, "onsite_ai_result_stale", "原请求已结束核实，迟到结果未采用")
    try:
        fresh = await authorized(session, ctx, req, site)
        current = row.params["onsite"]
        if (current["revision"] != req.expected_revision or current.get("ai_run", {}).get("request_id") != key
                or current["phase"] in {"done", "cancelled"} or row.status in {"done", "cancelled"}
                or work.proposal_hash(await ai.evidence(session, row, site, lock=True)) != claim["source_hash"]):
            raise ai.problem(409, "onsite_ai_result_stale", "任务或依据已变化，生成结果未采用")
    except Exception:
        run.update(state="stale", finished_at=ai.now().isoformat(),
                   error={"code": "onsite_ai_result_stale", "message": "权限、任务或依据已变化，结果未采用"})
        save_run(row, run)
        await session.commit()
        # Never leak the current task to an identity revoked during generation.
        raise ai.problem(409, "onsite_ai_result_stale", "权限、任务或依据已变化，结果未采用") from None
    if failure:
        run.update(state=failure[0], error=failure[1])
    else:
        change = work.Change(action="save_proposal", expected_revision=req.expected_revision,
                             items=items, note="AI 起草方案；仍须人工核实、审核及实施")
        value = work.prepare_change(row.params["onsite"], change, "seo", site.canonical_domain, fresh.user_id)
        row.status, row.completion_evidence = "in_progress", None
        value["ai_proposal"] = {"summary": "AI 起草，事实和适用条件仍须人工核对；未修改官网",
            "items": reasons, "missing_information": sorted({m for i in reasons for m in i["missing_information"]}),
            "proposal_revision": value["revision"]}
        row.params = {**row.params, "onsite": value}
        run.update(state="ready")
    run["finished_at"] = ai.now().isoformat()
    save_run(row, run)
    await session.commit()
    if cancelled:
        raise asyncio.CancelledError()
    return {**onsite.public(row, True, site.site_settings), "replayed": False}
