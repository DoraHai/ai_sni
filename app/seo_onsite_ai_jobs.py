"""Durable, at-most-once dispatch of manually queued SEO proposals.

The existing SeoTask JSON ledger is the queue. A committed running claim is
never reclaimed for another provider attempt: interrupted work becomes unknown.
No browser task, model fallback, new table or automatic paid retry is involved.
"""
import asyncio
import logging
from copy import deepcopy
from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from app import onsite_workflow as work, seo_onsite_ai as ai
from app.api import seo_onsite as onsite, seo_onsite_ai as api
from app.config import get_settings
from app.database import async_session_factory
from app.models.module_workspace import SeoSite
from app.models.seo_cockpit import SeoTask
from app.security.auth import AuthContext
from app.seo_demo_runtime import seo_scheduler_may_start

logger = logging.getLogger(__name__)
QUEUE_MAX_AGE_SECONDS = 86400


def finish(row, run, state, code, message):
    value = {**run, "state": state, "finished_at": ai.now().isoformat(),
             "error": {"code": code, "message": message}}
    api.save_run(row, value)
    return value


def expired(run):
    try:
        return (ai.now() - datetime.fromisoformat(run["started_at"])).total_seconds() > ai.LEASE_SECONDS
    except (KeyError, TypeError, ValueError):
        return True  # malformed legacy leases must never trigger another call


async def validate_current(session, ctx, req, site, row, run):
    fresh = await api.authorized(session, ctx, req, site)
    api.execution_enabled(site)
    current = row.params["onsite"]
    if (current["revision"] != req.expected_revision
            or current.get("ai_run", {}).get("request_id") != str(req.request_id)
            or current["phase"] in {"done", "cancelled"} or row.status in {"done", "cancelled"}):
        raise ai.problem(409, "onsite_ai_result_stale", "任务或版本已变化")
    facts = await ai.evidence(session, row, site, lock=True)
    if work.proposal_hash(facts) != run["source_hash"]:
        raise ai.problem(409, "onsite_ai_source_changed", "方案依据已变化")
    return fresh, facts


async def execute_request(task_id, tenant_id, site_id, key, *, sessions=None):
    """Claim one exact nonce. Separate DB transactions surround the provider call.

    Site-then-task lock order matches API writes; skip_locked lets competing
    workers move on. The committed claim ID fences cancellation and late output.
    """
    sessions = sessions or async_session_factory
    async with sessions() as session:
        site = await session.get(SeoSite, site_id, with_for_update={"skip_locked": True})
        if not site or site.tenant_id != tenant_id:
            return None
        row = await session.get(SeoTask, task_id, with_for_update={"skip_locked": True})
        if not row or (row.tenant_id, row.site_id, row.module, row.action_type) != (
                tenant_id, site_id, "seo", onsite.ACTION_TYPE):
            return None
        run = deepcopy((row.params.get("onsite_ai_requests") or {}).get(key))
        if not run:
            return None
        if run["state"] == "running":
            if expired(run):
                finish(row, run, "unknown", "onsite_ai_interrupted", "调用中断或超时，结果未核实；原请求不会自动重试")
                await session.commit()
                return "unknown"
            return "running"
        if run["state"] != "queued":
            return run["state"]
        req = api.Request(tenant_id=tenant_id, site_id=site_id, request_id=key,
                          expected_revision=run["source_revision"], mode=run["mode"])
        ctx = AuthContext(run["actor_user_id"], "", "", run.get("actor_tenant_id"), {})
        try:
            fresh, facts = await validate_current(session, ctx, req, site, row, run)
            if (ai.now() - datetime.fromisoformat(run["queued_at"])).total_seconds() > QUEUE_MAX_AGE_SECONDS:
                raise ai.problem(409, "onsite_ai_queue_expired", "排队超过一天，请人工核对后重新申请")
        except HTTPException:
            finish(row, run, "stale", "onsite_ai_request_stale", "权限、服务、任务或依据已变化，未调用供应商")
            await session.commit()
            return "stale"
        # Persist the call intent BEFORE the HTTP request. Even a crash directly
        # after this commit is unknown, never a reason to repeat a paid attempt.
        run.update(state="running", started_at=ai.now().isoformat(), claim_id=str(uuid4()))
        api.save_run(row, run)
        await session.commit()
    failure, cancelled = None, False
    try:
        async with asyncio.timeout(55):
            raw = await ai.generate(facts, tenant_id, site_id, fresh.user_id, task_id, key,
                                    expected_route=run["provider_metadata"])
        items, reasons = ai.validate_result(raw, facts)
    except (Exception, asyncio.CancelledError) as exc:
        failure = api.failed_state(exc)
        cancelled = isinstance(exc, asyncio.CancelledError)
    try:
        async with sessions() as session:
            site = await session.get(SeoSite, site_id, with_for_update=True)
            row = await session.get(SeoTask, task_id, with_for_update=True)
            api.task_matches(row, req)
            current_run = deepcopy((row.params.get("onsite_ai_requests") or {}).get(key))
            if not current_run or current_run["state"] != "running" or current_run.get("claim_id") != run["claim_id"]:
                return current_run["state"] if current_run else None
            if expired(current_run):
                finish(row, current_run, "unknown", "onsite_ai_interrupted", "原调用已超过核实时限，迟到结果未采用")
                await session.commit()
                return "unknown"
            try:
                fresh, _ = await validate_current(session, ctx, req, site, row, current_run)
            except HTTPException:
                finish(row, current_run, "stale", "onsite_ai_result_stale", "权限、服务、任务或依据已变化，结果未采用")
                await session.commit()
                return "stale"
            if failure:
                current_run.update(state=failure[0], error=failure[1])
            else:
                change = work.Change(action="save_proposal", expected_revision=req.expected_revision,
                                     items=items, note="AI 起草方案；仍须人工核实、审核及实施")
                value = work.prepare_change(row.params["onsite"], change, "seo", site.canonical_domain, fresh.user_id)
                row.status, row.completion_evidence = "in_progress", None
                value["ai_proposal"] = {"summary": "AI 起草，事实和适用条件仍须人工核对；未修改官网",
                    "items": reasons, "missing_information": sorted({m for i in reasons for m in i["missing_information"]}),
                    "proposal_revision": value["revision"]}
                row.params = {**row.params, "onsite": value}
                current_run.update(state="ready")
            current_run["finished_at"] = ai.now().isoformat()
            api.save_run(row, current_run)
            await session.commit()
            return current_run["state"]
    finally:
        if cancelled:
            raise asyncio.CancelledError()


async def run_onsite_ai_jobs(*, sessions=None):
    """Every 10s: bounded durable scan, including previous-process running leases."""
    settings = get_settings()
    if not seo_scheduler_may_start(settings) or not settings.seo_external_actions_enabled:
        return
    sessions = sessions or async_session_factory
    async with sessions() as session:
        candidates = list((await session.execute(select(SeoTask.id, SeoTask.tenant_id, SeoTask.site_id,
                SeoTask.params["onsite"]["ai_run"]["request_id"].astext).where(
            SeoTask.module == "seo", SeoTask.action_type == onsite.ACTION_TYPE,
            SeoTask.params["onsite"]["ai_run"]["state"].astext.in_(["queued", "running"]))
            .order_by(SeoTask.updated_at, SeoTask.id).limit(20))).all())
    # Each candidate owns independent sessions. One failed DB operation cannot
    # poison the transaction for the next tenant. At most two concurrent calls.
    semaphore = asyncio.Semaphore(2)
    async def one(candidate):
        async with semaphore:
            try:
                await execute_request(*candidate, sessions=sessions)
            except Exception as exc:
                logger.warning("[SEO][onsite-ai] task=%s failure_type=%s", candidate[0], type(exc).__name__)
    await asyncio.gather(*(one(candidate) for candidate in candidates))
