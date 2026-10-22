"""Shared self-service policy. Never retain HTTP tokens in durable delegates."""
from datetime import datetime, time, timedelta, timezone
import hashlib
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import load_only

from app.models import GeoProject, GeoPrompt, GeoTrackingEngine, GeoVisibilityPatrolRun, GeoVisibilityPatrolSettings, Tenant, User
from app.models.geo_visibility_patrol import GeoVisibilityPatrolSettingEvent as Event
from app.security.advisor_scope import deny

MODE = "daily_self_service"
ENGINES = ("doubao", "deepseek", "qwen", "hunyuan", "wenxin", "kimi")
LABELS = ("豆包", "DeepSeek", "千问", "元宝（混元 API）", "文心", "Kimi")
BJ = ZoneInfo("Asia/Shanghai")


def engine_states_query(tenant_ids):
    # Self-service must not load legacy tenant credential columns, even unused.
    return select(GeoTrackingEngine).where(GeoTrackingEngine.tenant_id.in_(tenant_ids)).options(load_only(
        GeoTrackingEngine.id, GeoTrackingEngine.tenant_id, GeoTrackingEngine.engine_key,
        GeoTrackingEngine.enabled, GeoTrackingEngine.sort_order, raiseload=True))


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(value):
    if value is None:
        return None
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)).isoformat().replace("+00:00", "Z")


def day_bounds(now=None):
    now = (now or datetime.now(BJ)).astimezone(BJ)
    start = datetime.combine(now.date(), time(), BJ)
    return (start.astimezone(timezone.utc).replace(tzinfo=None),
            (start + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None))


def is_auto(run):
    return getattr(run, "auto_day", None) is not None and (run.summary or {}).get("self_service", {}).get("mode") == MODE


def manual_condition():
    r = GeoVisibilityPatrolRun
    return or_(
        r.trigger.in_(("manual", "contract_retest")) & (func.coalesce(r.summary["reservation_only"].as_boolean(), False).is_(False)),
        (r.trigger == "quota_history") & (r.summary["manual_visibility"].as_boolean().is_(True)),
    ) & r.auto_day.is_(None)


async def manual_quota(session, tenant_id):
    from app.security.advisor_quota import STATE
    start, end = day_bounds()
    used = await session.scalar(select(func.count()).select_from(GeoVisibilityPatrolRun).where(
        GeoVisibilityPatrolRun.tenant_id == tenant_id, GeoVisibilityPatrolRun.created_at >= start,
        GeoVisibilityPatrolRun.created_at < end, manual_condition(),
        func.coalesce(GeoVisibilityPatrolRun.summary[STATE].as_string(), "") != "refunded",
    ).execution_options(advisor_scope_control=True))
    limit = await session.scalar(select(GeoVisibilityPatrolSettings.manual_daily_limit).where(
        GeoVisibilityPatrolSettings.tenant_id == tenant_id).execution_options(advisor_scope_control=True))
    return {"used": int(used or 0), "limit": 10 if limit is None else limit}


async def check_manual_quota(session, tenant_id):
    quota = await manual_quota(session, tenant_id)
    if quota["used"] >= quota["limit"]:
        deny(429, "ADVISOR_VISIBILITY_DAILY_LIMIT", f"今日该客户手动检测已用 {quota['used']}/{quota['limit']}，所有顾问共享；失败且无结果会退回次数")
    return quota


def snapshot(settings):
    return {"enabled": bool(settings.self_service_enabled), "admin_locked": bool(settings.admin_locked),
            "schedule_mode": settings.schedule_mode, "owner_user_id": settings.owner_user_id,
            "manual_daily_limit": settings.manual_daily_limit,
            "legacy_schedule": {"enabled": bool(settings.enabled), "window_start_hour": settings.window_start_hour,
                "window_end_hour": settings.window_end_hour, "interval_hours": settings.interval_hours,
                "prompt_limit": settings.prompt_limit, "engine_keys": settings.engine_keys}}


def audit(session, settings, ctx, action, before, reason=None, *, quota=False):
    session.add(Event(tenant_id=settings.tenant_id, actor_user_id=ctx.user_id,
        actor_role="advisor" if ctx.advisor_scope is not None else "admin", action=action,
        before=before, after=snapshot(settings), reason=reason,
        revision=settings.manual_limit_revision if quota else settings.revision))


async def locked_settings(session, tenant_id):
    from app.geo.content.geo_scheduler import current_patrol_settings, lock_scheduler_tenant
    if not await lock_scheduler_tenant(session, tenant_id):
        raise HTTPException(404, "客户不存在")
    row = await current_patrol_settings(session, tenant_id)
    if row is None:
        row = GeoVisibilityPatrolSettings(tenant_id=tenant_id)
        session.add(row)
        await session.flush()
    return row


def check_revision(actual, expected):
    if actual != expected:
        deny(409, "REVISION_CONFLICT", "设置已更新，请刷新后重试")


def require_admin(ctx):
    from app.security.geo_configuration_admin import require_geo_configuration_admin
    if ctx.advisor_scope is not None:
        deny(403, "SELF_SERVICE_FORBIDDEN", "只有平台管理员可执行此操作")
    require_geo_configuration_admin(ctx)
    if not ctx.can_edit("geo.content"):
        deny(403, "SELF_SERVICE_FORBIDDEN", "缺少 GEO 内容管理权限")


async def advisor_scope(session, ctx, request=None, *, enabled=False):
    from app.security.advisor_visibility import check_visibility_scope
    from app.security.advisor_write_reads import assigned_scope
    if ctx.advisor_scope is None:
        deny(403, "SELF_SERVICE_FORBIDDEN", "只有负责顾问可修改自动检测开关")
    ctx.ensure_tenant(ctx.tenant_id)
    request = request or SimpleNamespace(state=SimpleNamespace())
    if enabled:
        await check_visibility_scope(session, ctx, request)
    else:
        # An assigned project may currently have neither businesses nor questions.
        # Closing a delegate must still be possible, under the tenant lock.
        await session.scalar(select(Tenant.id).where(Tenant.id == ctx.tenant_id).with_for_update())
        from app.geo.project_workflows import advisor_available
        projects, _ = await assigned_scope(session, ctx)
        if not projects or not await advisor_available(session, ctx.tenant_id, ctx.user_id, advisor_scope=ctx.advisor_scope):
            deny(403, 'ADVISOR_ASSIGNMENT_REQUIRED', '当前客户没有分配给你的有效项目')
        request.state.advisor_visibility_prompt_ids = []
    projects, _ = await assigned_scope(session, ctx)
    return {"project_ids": sorted(projects), "prompt_ids": list(request.state.advisor_visibility_prompt_ids)}


async def scope_fingerprint(session, tenant_id, project_ids, prompt_ids):
    from app.geo.project_scope import binding
    from app.geo.project_workflows import plan_for
    from app.models import GeoOptimizationUnit
    projects = list(await session.scalars(select(GeoProject).where(
        GeoProject.tenant_id == tenant_id, GeoProject.id.in_(project_ids)).order_by(GeoProject.id)
        .execution_options(populate_existing=True)))
    prompts = list((await session.execute(select(GeoPrompt.id, GeoPrompt.unit_id, GeoOptimizationUnit.business_id, GeoPrompt.question)
        .join(GeoOptimizationUnit, GeoPrompt.unit_id == GeoOptimizationUnit.id).where(
            GeoPrompt.tenant_id == tenant_id, GeoPrompt.id.in_(prompt_ids)).order_by(GeoPrompt.id))).all())
    return {"projects": [{"id": p.id, "status": p.status, "binding": binding(p),
                           "advisor_user_id": plan_for(p).get("advisor_user_id")} for p in projects],
            "prompts": [[p.id, p.unit_id, p.business_id, hashlib.sha256(p.question.encode('utf-8')).hexdigest()] for p in prompts]}


def platforms(rows, last_run=None):
    from app.geo.content.engine_providers import resolve_platform_engine_credentials
    from app.geo.content.engine_identity import trusted_engine_source
    enabled = {r.engine_key for r in rows if r.enabled}
    auth_errors = {i.get("engine") for i in (last_run.items or []) if i.get("platform_status") == "auth_error"} if last_run else set()
    result = []
    for key, label in zip(ENGINES, LABELS):
        llm = resolve_platform_engine_credentials(key) if key in enabled else None
        status = "disabled" if key not in enabled else "not_configured"
        if llm and trusted_engine_source(key, llm.get("provider"), llm.get("model")):
            status = "auth_error" if key in auth_errors else "available"
        result.append({"engine_key": key, "label": label, "status": status})
    return result


def next_run(tenant_id, *, now=None, claimed=False):
    now = (now or datetime.now(BJ)).astimezone(BJ)
    target = datetime.combine(now.date(), time(8 + tenant_id % 4, 5), BJ)
    if claimed or now > datetime.combine(now.date(), time(11, 5), BJ):
        target += timedelta(days=1)
    elif now > target:
        target = now.replace(minute=5, second=0, microsecond=0) + timedelta(hours=1)
    return target.isoformat()


def last_run_payload(row):
    if row is None:
        return None
    counts = {key: {"engine_key": key, "success": 0, "failed": 0, "skipped": 0} for key in ENGINES}
    for cell in row.items or []:
        if cell.get("engine") in counts:
            key = "success" if cell.get("ok") else "skipped" if cell.get("skipped_reason") else "failed"
            counts[cell["engine"]][key] += 1
    totals = {name: sum(c[name] for c in counts.values()) for name in ("success", "failed", "skipped")}
    status = row.status
    if status == "completed":
        status = "success" if totals["success"] and not totals["failed"] and not totals["skipped"] else "partial_success" if totals["success"] else "failed"
    return {"id": row.id, "created_at": iso(row.created_at), "started_at": iso(row.started_at),
            "finished_at": iso(row.finished_at), "status": status, **totals, "platforms": list(counts.values())}


async def state_payload(session, tenant_id, ctx, *, row=None, bundle=None):
    """Shared view. Admin pagination may supply batched reference data."""
    if bundle is None:
        row = row or await session.get(GeoVisibilityPatrolSettings, tenant_id)
        engines = list(await session.scalars(engine_states_query([tenant_id])))
        last = await session.scalar(select(GeoVisibilityPatrolRun).where(GeoVisibilityPatrolRun.tenant_id == tenant_id,
            GeoVisibilityPatrolRun.auto_day.is_not(None)).order_by(GeoVisibilityPatrolRun.id.desc()).limit(1))
        inflight = bool(await session.scalar(select(GeoVisibilityPatrolRun.id).where(GeoVisibilityPatrolRun.tenant_id == tenant_id,
            GeoVisibilityPatrolRun.status.in_(("pending", "running"))).limit(1).execution_options(advisor_scope_control=True)))
        claimed_today = bool(await session.scalar(select(GeoVisibilityPatrolRun.id).where(
            GeoVisibilityPatrolRun.tenant_id == tenant_id, GeoVisibilityPatrolRun.auto_day == datetime.now(BJ).date())
            .execution_options(advisor_scope_control=True)))
        quota = await manual_quota(session, tenant_id)
        users = dict((await session.execute(select(User.id, User.display_name).where(User.id.in_(
            [i for i in (row.owner_user_id, row.opened_by, row.last_changed_by) if i] if row else [])))).all())
    else:
        engines, last, inflight, quota, users = bundle
        claimed_today = bool(last and last.auto_day == datetime.now(BJ).date())
    def actor(ident):
        return {"user_id": ident, "display_name": users.get(ident) or "顾问"} if ident else None
    enabled = bool(row and row.self_service_enabled)
    statuses = platforms(engines, last)
    blocked = row.blocked_reason if row else None
    if blocked == 'in_flight' and not inflight:
        blocked = None
    if enabled and last and last.error in {'authorization_changed', 'daily_budget_exhausted'}:
        blocked = last.error
    locked = bool(row and row.admin_locked)
    coverage = {"project_ids": [], "prompt_count": 0, "max_prompts": 20}
    toggle = False
    can_enable = False
    if ctx.advisor_scope is not None:
        from app.config import get_settings
        scope = await advisor_scope(session, ctx, enabled=False)
        toggle = bool(get_settings().advisor_scoped_content_writes_enabled)
        try:
            current = await advisor_scope(session, ctx, enabled=True)
            coverage = {"project_ids": current["project_ids"], "prompt_count": len(current["prompt_ids"]), "max_prompts": 20}
            can_enable = toggle and not locked and any(s["status"] == "available" for s in statuses)
            blocked = (blocked if enabled else None) or (None if can_enable else "no_platforms")
            if len(current['prompt_ids']) * len(ENGINES) > get_settings().geo_patrol_max_cells_per_run:
                can_enable, blocked = False, 'cell_limit'
        except HTTPException as exc:
            if exc.status_code != 409 and not (exc.status_code == 403 and isinstance(exc.detail, dict)
                    and exc.detail.get('code') == 'ADVISOR_ASSIGNMENT_REQUIRED'):
                raise
            coverage["project_ids"] = scope["project_ids"]
            blocked = "no_prompts"
        if not toggle:
            blocked = "write_disabled"
    elif row and row.owner_scope:
        coverage = {"project_ids": row.owner_scope.get("project_ids", []), "prompt_count": row.owner_scope.get("prompt_count", 0), "max_prompts": 20}
    if locked:
        blocked = "admin_locked"
    return {"tenant_id": tenant_id, "schedule_mode": row.schedule_mode if row else "legacy", "enabled": enabled,
        "admin_locked": locked, "lock_reason": row.lock_reason if row else None,
        "owner": actor(row.owner_user_id) if row else None, "opened_at": iso(row.opened_at) if row else None,
        "opened_by": actor(row.opened_by) if row else None, "last_changed_by": actor(row.last_changed_by) if row else None,
        "last_changed_at": iso(row.last_changed_at) if row else None, "last_run": last_run_payload(last),
        "next_run_estimate": next_run(tenant_id, claimed=claimed_today) if enabled and not locked and not blocked else None,
        "platforms": statuses, "manual_quota": quota, "manual_limit_revision": row.manual_limit_revision if row else 0,
        "can_toggle": toggle and not locked, "can_enable": can_enable,
        "blocked_reason": blocked, "revision": row.revision if row else 0, "coverage": coverage, "in_flight": inflight}
