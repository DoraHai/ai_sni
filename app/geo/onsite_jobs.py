"""Durable execution for GEO onsite AI proposals.

The provider call is deliberately single-attempt.  Once it starts, a process
loss is exposed as ``unknown`` and must be resolved by a person; startup
recovery never repeats a possibly billed request.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import onsite_workflow as work
from app.api_controls import ControlDenied
from app.api_metering import MeteringUnavailable, background_scope
from app.geo import onsite_ai
from app.geo.ai_client import DeepSeekError, chat_json
from app.geo.content.ai_settings import resolve_llm_credentials
from app.geo.project_scope import project_scope
from app.geo.tenant_scope import ensure_geo_entitlement
from app.models import GeoActionTicket, GeoAsyncJob, GeoProject
from app.models.role import Role
from app.models.user import User
from app.security.auth import AuthContext

PENDING_BATCH_LIMIT = 5
PENDING_TICK_SECONDS = 10
_worker_status: dict[str, Any] = {
    "enabled": False,
    "state": "unverified",
    "verified": False,
    "evidence": "none",
    "last_tick_at": None,
    "last_attempted": 0,
    "last_completed": 0,
    "last_error": None,
}


class PendingBatchError(RuntimeError):
    """One or more queued jobs failed before returning a worker result."""


def pending_worker_status() -> dict[str, Any]:
    return dict(_worker_status)


async def run_pending_batch(*, session_factory=None, runner=None,
                            limit: int = PENDING_BATCH_LIMIT) -> dict[str, int]:
    """Consume recent queued jobs; never selects or replays ``running`` jobs."""
    from app.database import async_session_factory
    from app.geo.content.async_jobs import (
        KIND_ONSITE_PROPOSAL, STALE_PENDING_SECONDS, run_job_synchronously,
    )
    from app.geo.tenant16_demo import DEMO_TENANT_ID

    factory = session_factory or async_session_factory
    execute = runner or run_job_synchronously
    cutoff = datetime.utcnow() - timedelta(seconds=STALE_PENDING_SECONDS)
    async with factory() as session:
        rows = list(await session.execute(
            select(GeoAsyncJob.id, GeoAsyncJob.tenant_id).where(
                GeoAsyncJob.kind == KIND_ONSITE_PROPOSAL,
                GeoAsyncJob.status == "pending",
                GeoAsyncJob.tenant_id != DEMO_TENANT_ID,
                GeoAsyncJob.created_at >= cutoff,
            ).order_by(GeoAsyncJob.id).limit(max(1, min(int(limit), 20)))
        ))
    outcomes = await asyncio.gather(
        *(execute(int(row.id), int(row.tenant_id)) for row in rows),
        return_exceptions=True,
    )
    failures = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
    if failures:
        kinds = ",".join(sorted({type(failure).__name__ for failure in failures}))
        raise PendingBatchError(
            f"{len(failures)} queued job runner(s) failed ({kinds})"
        )
    completed = sum(
        1 for outcome in outcomes
        if isinstance(outcome, dict) and outcome.get("status") not in {"conflict", "blocked"}
    )
    return {"attempted": len(rows), "completed": completed}


async def supervise_pending_jobs() -> None:
    """Continuously recover committed submissions whose HTTP callback was lost."""
    from app.config import get_settings

    enabled = bool(getattr(get_settings(), "geo_async_worker_enabled", True))
    _worker_status.update(
        enabled=enabled,
        state="unverified" if enabled else "disabled",
        verified=not enabled,
        evidence="none" if enabled else "disabled",
    )
    if not enabled:
        return
    while True:
        try:
            try:
                result = await run_pending_batch()
                _worker_status.update(
                    state="active", last_tick_at=onsite_ai.now_iso(),
                    last_attempted=result["attempted"], last_completed=result["completed"],
                    last_error=None, verified=True, evidence="tick",
                )
            except Exception as exc:  # noqa: BLE001
                _worker_status.update(
                    state="degraded", last_tick_at=onsite_ai.now_iso(),
                    last_error=type(exc).__name__, verified=True, evidence="error",
                )
            await asyncio.sleep(PENDING_TICK_SECONDS)
        except asyncio.CancelledError:
            _worker_status.update(state="stopped", verified=True, evidence="stopped")
            raise


def _meta(job: GeoAsyncJob) -> dict[str, Any]:
    return dict(job.request_meta or {})


async def _actor_context(
    session: AsyncSession, actor_user_id: int, tenant_id: int, *, lock: bool
) -> AuthContext:
    user = await session.get(User, actor_user_id, with_for_update=lock, populate_existing=True)
    if user is None or not user.is_active:
        raise HTTPException(403, "发起账号已停用，AI 任务停止")
    role = await session.get(Role, user.role_id, with_for_update=lock, populate_existing=True)
    permissions = dict(role.permissions or {}) if role else {}
    ctx = AuthContext(
        user_id=user.id,
        username=user.username,
        role_name=role.name if role else "?",
        tenant_id=user.tenant_id,
        permissions=permissions,
    )
    ctx.ensure_tenant(tenant_id)
    return ctx


async def _current_scope(
    session: AsyncSession, job: GeoAsyncJob, *, lock: bool
) -> tuple[dict[str, Any], AuthContext, GeoProject, GeoActionTicket, dict[str, Any]]:
    # Imports are local to avoid a router/worker import cycle at application boot.
    from app.geo.onsite_routes import PREFIX, _proposal_snapshot, can_operate

    meta = _meta(job)
    tenant_id = int(job.tenant_id)
    project_id = int(meta["project_id"])
    task_id = int(meta["task_id"])
    actor_user_id = int(meta["actor_user_id"])
    await ensure_geo_entitlement(
        session, tenant_id, allow_demo_read=False, lock_binding=lock
    )
    await project_scope(session, tenant_id, project_id)
    ctx = await _actor_context(session, actor_user_id, tenant_id, lock=lock)
    project = await session.get(
        GeoProject, project_id, with_for_update=lock, populate_existing=True
    )
    row = await session.get(
        GeoActionTicket, task_id, with_for_update=lock, populate_existing=True
    )
    if (
        project is None
        or project.tenant_id != tenant_id
        or row is None
        or row.tenant_id != tenant_id
        or not (row.advice_code or "").startswith(PREFIX)
        or (row.progress or {}).get("onsite", {}).get("project_id") != project_id
    ):
        raise HTTPException(404, "当前项目的站内任务不存在")
    if not await can_operate(session, ctx, project, lock_advisor=lock):
        raise HTTPException(403, "顾问分配、账号权限或项目服务状态已变化")
    value = dict(row.progress["onsite"])
    run = dict(value.get("ai_run") or {})
    if (
        run.get("request_id") != meta.get("request_id")
        or int(run.get("job_id") or 0) != int(job.id)
    ):
        raise HTTPException(409, "AI 请求已被替代，迟到结果不会写入")
    if int(value.get("revision") or 0) != int(meta["expected_revision"]):
        raise HTTPException(409, "任务版本已变化，AI 结果不会写入")
    snapshot = await _proposal_snapshot(session, project, row)
    onsite_ai.planning_preflight(snapshot)
    if snapshot["source_hash"] != meta.get("source_hash"):
        raise HTTPException(409, "项目范围或公开资料版本已变化，AI 结果不会写入")
    return meta, ctx, project, row, snapshot


async def _set_run(
    session: AsyncSession,
    job: GeoAsyncJob,
    *,
    state: str,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    meta = _meta(job)
    row = await session.get(
        GeoActionTicket, int(meta["task_id"]), with_for_update=True, populate_existing=True
    )
    if row is None:
        return
    value = dict((row.progress or {}).get("onsite") or {})
    run = dict(value.get("ai_run") or {})
    if (
        run.get("request_id") != meta.get("request_id")
        or int(run.get("job_id") or 0) != int(job.id)
    ):
        return
    run["state"] = state
    if state == "running":
        run["started_at"] = onsite_ai.now_iso()
    elif state not in {"queued"}:
        run["finished_at"] = onsite_ai.now_iso()
    if error:
        run["error"] = error[:500]
    else:
        run.pop("error", None)
    if extra:
        run.update({key: value for key, value in extra.items() if value is not None})
    value["ai_run"] = run
    row.progress = {**(row.progress or {}), "onsite": value}
    row.updated_at = datetime.utcnow()
    await session.commit()


async def _terminal(
    session: AsyncSession,
    job: GeoAsyncJob,
    state: str,
    message: str,
    **metadata: Any,
) -> dict[str, Any]:
    job_id = int(job.id)
    await session.rollback()
    job = await session.get(GeoAsyncJob, job_id, populate_existing=True)
    if job is None:
        return {"public_state": state, "message": message, **metadata}
    await _set_run(session, job, state=state, error=message, extra=metadata)
    return {"public_state": state, "message": message, **metadata}


async def execute_onsite_proposal(
    session: AsyncSession, job: GeoAsyncJob
) -> dict[str, Any]:
    """Execute one reserved request; never retry or change provider."""
    meta = _meta(job)
    if meta.get("cancel_requested"):
        await _set_run(session, job, state="cancelled", error="请求已取消")
        raise ValueError("已取消")

    try:
        meta, ctx, project, row, snapshot = await _current_scope(session, job, lock=True)
        credentials = onsite_ai.select_planning_credentials(
            await resolve_llm_credentials(session, int(job.tenant_id)) or {}
        )
        if not credentials.get("api_key"):
            raise HTTPException(409, "平台 AI 供应商尚未配置")
        if onsite_ai.planning_route(credentials) != meta.get("provider_route"):
            raise HTTPException(409, "AI 供应商或模型路由已变化，本次请求在计费前停止")
        system_prompt, user_prompt = onsite_ai.prompt_text(snapshot, meta["mode"])
        generation_options = onsite_ai.generation_options(credentials, snapshot)
        job = await session.get(
            GeoAsyncJob, int(job.id), with_for_update=True, populate_existing=True
        )
        if job is None:
            return {"public_state": "stale", "message": "AI 作业已不存在"}
        if _meta(job).get("cancel_requested"):
            await _set_run(session, job, state="cancelled", error="请求已取消")
            raise ValueError("已取消")
        current_meta = _meta(job)
        current_meta["provider_started_at"] = onsite_ai.now_iso()
        job.request_meta = current_meta
        await _set_run(session, job, state="running")
    except ValueError:
        raise
    except HTTPException as exc:
        return await _terminal(
            session, job, "stale", str(exc.detail), error_category="pre_execution"
        )

    try:
        with background_scope(
            tenant_id=int(job.tenant_id),
            module="geo",
            operation="onsite.ai_proposal",
            user_id=int(meta["actor_user_id"]),
            job_ref=f"geo-onsite-ai:{meta['task_id']}:{meta['request_id']}",
        ):
            result = await chat_json(
                system_prompt,
                user_prompt,
                timeout=45.0,
                api_key=credentials["api_key"],
                base_url=credentials["base_url"],
                model=credentials["model"],
                **generation_options,
            )
    except ControlDenied as exc:
        return await _terminal(
            session,
            job,
            "failed",
            "AI 请求未通过平台调用门禁，供应商未被调用",
            error_category="admission_denied",
            error_code=exc.code,
        )
    except MeteringUnavailable as exc:
        attempted = bool(exc.provider_attempted)
        return await _terminal(
            session,
            job,
            "unknown" if attempted else "failed",
            (
                "AI 供应商调用后计量结果未能确认，系统不会自动重试"
                if attempted
                else "AI 调用计量服务暂不可用，供应商未被调用"
            ),
            error_category=(
                "metering_finalize_unknown" if attempted else "admission_unavailable"
            ),
        )
    except DeepSeekError as exc:
        uncertain = exc.category in {"timeout", "network", "unknown"}
        state = "unknown" if uncertain else "failed"
        message = (
            "AI 供应商结果未知，系统不会自动重试；请人工核对调用记录"
            if uncertain
            else "AI 供应商请求失败，系统未自动重试"
        )
        return await _terminal(
            session,
            job,
            state,
            message,
            error_category=exc.category,
            error_code=exc.code,
            http_status=exc.status_code,
        )
    except Exception:
        return await _terminal(
            session,
            job,
            "unknown",
            "AI 调用结果未知，系统不会自动重试；请人工核对调用记录",
            error_category="unknown",
        )

    try:
        meta, ctx, project, row, fresh = await _current_scope(session, job, lock=True)
        job = await session.get(
            GeoAsyncJob, int(job.id), with_for_update=True, populate_existing=True
        )
        if job is None:
            return {"public_state": "stale", "message": "AI 作业已不存在"}
        if _meta(job).get("cancel_requested"):
            await _set_run(session, job, state="cancelled", error="请求已取消；迟到结果未保存")
            raise ValueError("已取消")
        current = dict(row.progress["onsite"])
        items, explanation = onsite_ai.validate_provider_result(
            result,
            current_items=current["items"],
            facts=fresh["facts"],
            domain=project.canonical_domain,
        )
        deterministic_missing = []
        if not fresh["questions"]:
            deterministic_missing.append("缺少当前项目服务计划中的有效重点问题")
        explanation["missing_information"] = list(
            dict.fromkeys(
                [*deterministic_missing, *explanation.get("missing_information", [])]
            )
        )[:50]
        change = work.Change(
            action="save_proposal",
            expected_revision=int(meta["expected_revision"]),
            items=items,
            note="AI 起草，等待人工核对",
        )
        updated = work.prepare_change(
            current, change, "geo", project.canonical_domain, ctx.user_id
        )
        explanation["proposal_revision"] = updated["revision"]
        updated["ai_proposal"] = explanation
        updated["ai_run"] = {
            **dict(current["ai_run"]),
            "state": "ready",
            "proposal_revision": updated["revision"],
            "finished_at": onsite_ai.now_iso(),
        }
        row.progress = {**(row.progress or {}), "onsite": updated}
        row.status = "doing"
        row.updated_at = datetime.utcnow()
        await session.commit()
        return {
            "public_state": "ready",
            "proposal_revision": updated["revision"],
        }
    except ValueError:
        raise
    except HTTPException as exc:
        state = "failed" if exc.status_code == 422 else "stale"
        message = (
            "AI 返回内容未通过站内方案安全校验"
            if state == "failed"
            else str(exc.detail)
        )
        return await _terminal(
            session, job, state, message, error_category="result_validation"
        )
    except Exception:
        return await _terminal(
            session,
            job,
            "unknown",
            "AI 结果保存状态未知，系统不会自动重试；请人工核对",
            error_category="save_unknown",
        )


async def recover_interrupted_job(session: AsyncSession, job: GeoAsyncJob) -> str:
    """Close an unowned running job without repeating its paid request."""
    meta = _meta(job)
    row = await session.get(
        GeoActionTicket, int(meta.get("task_id") or 0), with_for_update=True,
        populate_existing=True,
    )
    run: dict[str, Any] = {}
    if row is not None:
        value = dict((row.progress or {}).get("onsite") or {})
        run = dict(value.get("ai_run") or {})
        if (
            run.get("request_id") == meta.get("request_id")
            and int(run.get("job_id") or 0) == int(job.id)
            and run.get("state") == "ready"
        ):
            job.status = "succeeded"
            job.result_meta = {
                "public_state": "ready",
                "proposal_revision": run.get("proposal_revision"),
            }
            job.finished_at = datetime.utcnow()
            await session.commit()
            return "ready"
        if run.get("request_id") == meta.get("request_id") and int(
            run.get("job_id") or 0
        ) == int(job.id):
            state = "cancelled" if meta.get("cancel_requested") else "unknown"
            message = (
                "请求已取消；中断期间的迟到结果不会保存"
                if state == "cancelled"
                else "服务中断后无法确认付费请求结果，系统不会自动重试"
            )
            run.update(
                state=state,
                error=message,
                finished_at=onsite_ai.now_iso(),
            )
            value["ai_run"] = run
            row.progress = {**(row.progress or {}), "onsite": value}
            row.updated_at = datetime.utcnow()
    state = "cancelled" if meta.get("cancel_requested") else "unknown"
    job.status = "cancelled" if state == "cancelled" else "failed"
    job.error = (
        "已取消" if state == "cancelled" else "服务中断，AI 供应商结果未知，系统不会自动重试"
    )
    job.result_meta = {
        "public_state": state, "error_category": "interrupted", "message": job.error
    }
    job.finished_at = datetime.utcnow()
    await session.commit()
    return state


async def expire_queued_job(session: AsyncSession, job: GeoAsyncJob, message: str) -> None:
    """Close an unclaimed request without implying that a provider was called."""
    await _set_run(
        session, job, state="stale", error=message,
        extra={"error_category": "queue_timeout"},
    )
    job = await session.get(GeoAsyncJob, int(job.id), populate_existing=True)
    if job is None:
        return
    job.status = "failed"
    job.error = message
    job.result_meta = {
        "public_state": "stale", "error_category": "queue_timeout", "message": message
    }
    job.finished_at = datetime.utcnow()
    await session.commit()
