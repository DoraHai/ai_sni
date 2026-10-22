"""Durable daily producer and two globally owned self-service worker slots."""
import asyncio
import logging
from datetime import datetime, time
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.geo.content import autopatrol as policy
from app.models import GeoVisibilityPatrolRun as Run, GeoVisibilityPatrolSettings as Settings, GeoTrackingEngine
from app.security.advisor_visibility import AdvisorVisibilityUnavailable

logger = logging.getLogger(__name__)
SLOTS = 2


async def claim_legacy_day(session, tenant_id, *, now=None):
    """Called under the same tenant lock as every old and new producer."""
    start, end = policy.day_bounds(now)
    today = (now or datetime.now(policy.BJ)).astimezone(policy.BJ).date()
    if await session.scalar(select(Run.id).where(Run.tenant_id == tenant_id, Run.auto_day == today)):
        return
    legacy = await session.scalar(select(Run).where(Run.tenant_id == tenant_id, Run.trigger == "schedule",
        Run.created_at >= start, Run.created_at < end).order_by(Run.id).limit(1))
    if legacy:
        legacy.auto_day = today
        await session.flush()


async def validate_delegate(session, run):
    st = await session.scalar(select(Settings).where(Settings.tenant_id == run.tenant_id)
        .execution_options(populate_existing=True))
    frozen = (run.summary or {}).get("self_service") or {}
    if (st is None or st.schedule_mode != policy.MODE or not st.self_service_enabled or st.admin_locked
            or st.owner_user_id != run.created_by or st.owner_grant_id != (run.summary or {}).get("advisor_visibility_auth", {}).get("grant_id")
            or st.revision != frozen.get("revision")):
        raise AdvisorVisibilityUnavailable("authorization_changed")
    scope = frozen.get("scope") or {}
    fingerprint = await policy.scope_fingerprint(session, run.tenant_id, scope.get("project_ids", []),
        (run.summary or {}).get("advisor_visibility_prompt_ids") or [])
    if fingerprint != frozen.get("fingerprint"):
        raise AdvisorVisibilityUnavailable("authorization_changed")
    from app.geo.content.engine_providers import resolve_platform_engine_credentials
    for key, meta in (frozen.get("models") or {}).items():
        llm = resolve_platform_engine_credentials(key)
        if llm is None or {k: llm.get(k) for k in ("provider", "model")} != meta:
            raise AdvisorVisibilityUnavailable("authorization_changed")


async def enqueue_day(session, tenant_id, *, now=None):
    """No network work; transaction contains tenant lock, auth and unique claim."""
    from app.security.advisor_visibility import check_visibility_execution, check_visibility_scope
    from app.security.advisor_scope import AdvisorScope
    from app.models.advisor_tenant_grant import AdvisorTenantGrant
    from app.security.auth import AuthContext
    from app.geo.content.engine_providers import resolve_platform_engine_credentials
    from app.geo.tenant_scope import ensure_geo_entitlement, GeoEntitlementUnavailable
    now = (now or datetime.now(policy.BJ)).astimezone(policy.BJ)
    if not (time(8 + tenant_id % 4, 5) <= now.time().replace(tzinfo=None) <= time(11, 5, 59)):
        return None
    st = await policy.locked_settings(session, tenant_id)
    if st.schedule_mode != policy.MODE or not st.self_service_enabled or st.admin_locked:
        return None
    if await session.scalar(select(Run.id).where(Run.tenant_id == tenant_id, Run.auto_day == now.date())):
        return None
    if await session.scalar(select(Run.id).where(Run.tenant_id == tenant_id, Run.status.in_(("pending", "running")))):
        st.blocked_reason = "in_flight"
        return None
    from app.geo.retest import reserved_week
    if await reserved_week(session, tenant_id):
        st.blocked_reason = "reserved_retest"
        return None
    try:
        await ensure_geo_entitlement(session, tenant_id)
        # This context only selects questions; the complete user/role/grant
        # check below reconstructs authority from durable records, never JWT.
        grants = list(await session.scalars(select(AdvisorTenantGrant).where(
            AdvisorTenantGrant.user_id == st.owner_user_id, AdvisorTenantGrant.revoked_at.is_(None))))
        ctx = AuthContext(st.owner_user_id, "", "advisor", tenant_id, {"geo.assets": "edit", "geo.content": "edit"},
            advisor_scope=AdvisorScope(frozenset(g.tenant_id for g in grants), tenant_id, st.owner_grant_id))
        req = SimpleNamespace(state=SimpleNamespace())
        # Tenant -> user -> role -> grant locks must precede project locks.
        probe = Run(tenant_id=tenant_id, created_by=st.owner_user_id, auto_day=now.date(),
            summary={"self_service": {"mode": policy.MODE, "revision": st.revision,
                "scope": st.owner_scope or {}, "fingerprint": None},
                "advisor_visibility_auth": {"user_id": st.owner_user_id, "tenant_id": tenant_id, "grant_id": st.owner_grant_id}},
            engine_keys=[])
        # Resolve the persisted owner scope without expanding to other projects.
        await check_visibility_scope(session, ctx, req, lock=False)
        from app.security.advisor_write_reads import assigned_scope
        current_projects, _ = await assigned_scope(session, ctx)
        if set(current_projects) != set((st.owner_scope or {}).get('project_ids', [])):
            raise AdvisorVisibilityUnavailable('authorization_changed')
        prompt_ids = req.state.advisor_visibility_prompt_ids
        fingerprint = await policy.scope_fingerprint(session, tenant_id, (st.owner_scope or {}).get("project_ids", []), prompt_ids)
        saved = (st.owner_scope or {}).get("fingerprint", {})
        if fingerprint.get("projects") != saved.get("projects"):
            raise AdvisorVisibilityUnavailable("authorization_changed")
        engines = list(await session.scalars(select(GeoTrackingEngine).where(GeoTrackingEngine.tenant_id == tenant_id)))
        statuses = policy.platforms(engines)
        keys = [p["engine_key"] for p in statuses if p["status"] == "available"]
        if not keys:
            st.blocked_reason = "no_platforms"
            return None
        from app.config import get_settings
        from app.geo.content.patrol import count_patrol_runs_today
        max_cells = int(get_settings().geo_patrol_max_cells_per_run)
        if len(prompt_ids) * len(policy.ENGINES) > max_cells:
            st.blocked_reason = "no_prompts"
            return None
        used = await count_patrol_runs_today(session, tenant_id, classified=True)
        outer = max(1, min(int(get_settings().geo_patrol_max_runs_per_day or 24), 500))
        if used >= outer:
            st.blocked_reason = "daily_budget_exhausted"
            return None
        models = {key: {k: resolve_platform_engine_credentials(key).get(k) for k in ("provider", "model")} for key in keys}
        probe.engine_keys = keys
        probe.summary = {"advisor_visibility_prompt_ids": prompt_ids,
            "advisor_visibility_auth": {"user_id": st.owner_user_id, "tenant_id": tenant_id, "grant_id": st.owner_grant_id},
            "self_service": {"mode": policy.MODE, "revision": st.revision, "scope": st.owner_scope,
                "fingerprint": fingerprint, "models": models, "platforms": statuses}}
        await check_visibility_execution(session, probe, prompt_ids, lock=True)
    except (AdvisorVisibilityUnavailable, HTTPException, GeoEntitlementUnavailable):
        st.blocked_reason = "authorization_changed"
        return None
    run = Run(tenant_id=tenant_id, created_by=st.owner_user_id, auto_day=now.date(),
        trigger="self_service", status="pending", auto_persist=True, prefer_real=True,
        prompt_limit=20, engine_keys=keys, summary=probe.summary)
    # The unique index is the final arbiter even if another producer is added.
    try:
        async with session.begin_nested():
            session.add(run)
            await session.flush()
    except IntegrityError:
        return None
    st.last_scheduled_at = policy.utcnow()
    st.blocked_reason = None
    return run


async def scan_self_service_days():
    from app.database import async_session_factory
    from app.geo.tenant16_demo import DEMO_TENANT_ID
    cursor = 0
    while True:
        async with async_session_factory() as session:
            ids = list(await session.scalars(select(Settings.tenant_id).where(Settings.tenant_id > cursor,
                Settings.tenant_id != DEMO_TENANT_ID, Settings.schedule_mode == policy.MODE,
                Settings.self_service_enabled.is_(True)).order_by(Settings.tenant_id).limit(100)))
        if not ids:
            return
        for tenant_id in ids:
            async with async_session_factory() as session:
                try:
                    await enqueue_day(session, tenant_id)
                    await session.commit()
                except Exception:
                    await session.rollback()
                    logger.exception("self-service scheduling failed tenant=%s", tenant_id)
        cursor = ids[-1]


async def consume_slot(slot):
    from app.database import async_session_factory
    from app.geo.content.patrol import patrol_execution_lock, execute_patrol_run, PATROL_EXECUTION_PROTOCOL
    # Negative IDs are reserved exclusively for global slots; persisted IDs are positive.
    async with patrol_execution_lock(-1000000 - slot) as owned:
        if not owned:
            return
        async with async_session_factory() as session:
            rows = list(await session.scalars(select(Run).where(Run.trigger == "self_service", Run.auto_day.is_not(None),
                Run.status == "pending").order_by(Run.auto_day, Run.id).limit(100)))
            await session.commit()
            for row in rows:
                async with patrol_execution_lock(row.id) as acquired:
                    if not acquired:
                        continue
                    await session.refresh(row, with_for_update=True)
                    if row.status != "pending":
                        await session.commit()
                        continue
                    if row.auto_day != datetime.now(policy.BJ).date():
                        row.status, row.error, row.finished_at = "cancelled", "expired_queue_day", policy.utcnow()
                        await session.commit()
                        continue
                    # execute_patrol_run commits pending -> running before supplier calls.
                    await execute_patrol_run(session, row.id, tenant_id=row.tenant_id, execution_protocol=PATROL_EXECUTION_PROTOCOL)
                    return


async def consume_queue():
    await asyncio.gather(*(consume_slot(slot) for slot in range(SLOTS)))


async def supervise_queue():
    while True:
        try:
            await consume_queue()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("self-service consumer failed; retrying queue inspection")
        await asyncio.sleep(2)
