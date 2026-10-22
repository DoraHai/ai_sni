"""Narrow advisor switches and administrator stop/quota actions."""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator
from sqlalchemy import func, select

from app.database import get_session
from app.models import GeoTrackingEngine, GeoVisibilityPatrolRun as Run, GeoVisibilityPatrolSettings as Settings, Tenant, User
from app.models.geo_visibility_patrol import GeoVisibilityPatrolSettingEvent as Event
from app.security.auth import require_scoped_auth
from app.security.advisor_scope import deny
from app.geo.content import autopatrol as service

router = APIRouter(tags=["GEO 每日自动检测"])


class Toggle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: StrictInt = Field(gt=0)
    enabled: StrictBool
    expected_revision: StrictInt = Field(ge=0)


class AdminAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: StrictInt = Field(gt=0)
    action: Literal["force_disable", "unlock"]
    expected_revision: StrictInt = Field(ge=0)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class ManualLimit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: StrictInt = Field(gt=0)
    expected_revision: StrictInt = Field(ge=0)
    reason: str = Field(min_length=1, max_length=500)
    manual_daily_limit: StrictInt = Field(ge=0, le=100)

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


async def read_access(session, ctx, tenant_id):
    ctx.ensure_tenant(tenant_id)
    if ctx.advisor_scope is None:
        service.require_admin(ctx)
    else:
        await service.advisor_scope(session, ctx, enabled=False)


@router.get("/visibility-patrol/self-service")
async def get_self_service(tenant_id: int = Query(..., gt=0), ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    await read_access(session, ctx, tenant_id)
    return await service.state_payload(session, tenant_id, ctx)


@router.put("/visibility-patrol/self-service")
async def put_self_service(req: Toggle, request: Request, ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    ctx.ensure_tenant(req.tenant_id)
    if ctx.advisor_scope is None:
        deny(403, "SELF_SERVICE_FORBIDDEN", "只有负责顾问可修改自动检测开关")
    from app.security.advisor_write_routes import SELF_SERVICE_RULE
    bound = session.info.get("advisor_scoped_write")
    if bound is None or bound[0] is not ctx or bound[3] != SELF_SERVICE_RULE:
        deny(403, "SELF_SERVICE_FORBIDDEN", "缺少顾问开关授权范围")
    row = await service.locked_settings(session, req.tenant_id)
    service.check_revision(row.revision, req.expected_revision)
    if row.admin_locked:
        deny(423, "ADMIN_LOCKED", "管理员已锁定，请等待解除管理锁")
    scope = await service.advisor_scope(session, ctx, request, enabled=req.enabled)
    if bool(row.self_service_enabled) == req.enabled:
        return await service.state_payload(session, req.tenant_id, ctx, row=row)
    before = service.snapshot(row)
    if req.enabled:
        from app.config import get_settings
        if len(scope['prompt_ids']) * len(service.ENGINES) > get_settings().geo_patrol_max_cells_per_run:
            deny(409, 'CELL_LIMIT', '当前单轮上限不足以覆盖问题和六家平台，请由管理员核对')
        engines = list(await session.scalars(select(GeoTrackingEngine).where(GeoTrackingEngine.tenant_id == req.tenant_id)))
        if not any(p["status"] == "available" for p in service.platforms(engines)):
            deny(409, "NO_PLATFORMS", "六家国内平台均不可用，请等待平台配置")
        from app.geo.tenant_scope import ensure_geo_entitlement
        await ensure_geo_entitlement(session, req.tenant_id)
        if row.schedule_mode != service.MODE:
            from app.geo.content.autopatrol_queue import claim_legacy_day
            await claim_legacy_day(session, req.tenant_id)
            row.schedule_mode = service.MODE
            row.enabled = False
            row.revision += 1
            service.audit(session, row, ctx, "migrate", before, "首次切换，停用旧定时")
            before = service.snapshot(row)
        row.owner_user_id, row.owner_grant_id = ctx.user_id, ctx.advisor_scope.grant_id
        row.owner_scope = {"project_ids": scope["project_ids"], "prompt_count": len(scope["prompt_ids"]),
            "fingerprint": await service.scope_fingerprint(session, req.tenant_id, scope["project_ids"], scope["prompt_ids"])}
        row.opened_at, row.opened_by = service.utcnow(), ctx.user_id
    row.self_service_enabled = req.enabled
    row.blocked_reason = None
    row.revision += 1
    row.last_changed_by, row.last_changed_at = ctx.user_id, service.utcnow()
    service.audit(session, row, ctx, "enable" if req.enabled else "disable", before)
    await session.commit()
    return await service.state_payload(session, req.tenant_id, ctx, row=row)


@router.post("/visibility-patrol/self-service/admin-action")
async def admin_action(req: AdminAction, ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    service.require_admin(ctx)
    row = await service.locked_settings(session, req.tenant_id)
    service.check_revision(row.revision, req.expected_revision)
    before = service.snapshot(row)
    row.enabled = False
    row.self_service_enabled = False
    row.admin_locked = req.action == "force_disable"
    row.lock_reason = req.reason if row.admin_locked else None
    row.blocked_reason = "admin_locked" if row.admin_locked else None
    row.revision += 1
    row.last_changed_by, row.last_changed_at = ctx.user_id, service.utcnow()
    service.audit(session, row, ctx, req.action, before, req.reason)
    await session.commit()
    return await service.state_payload(session, req.tenant_id, ctx, row=row)


@router.put("/visibility-patrol/manual-limit")
async def put_manual_limit(req: ManualLimit, ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    service.require_admin(ctx)
    row = await service.locked_settings(session, req.tenant_id)
    service.check_revision(row.manual_limit_revision, req.expected_revision)
    if row.manual_daily_limit != req.manual_daily_limit:
        before = service.snapshot(row)
        row.manual_daily_limit = req.manual_daily_limit
        row.manual_limit_revision += 1
        service.audit(session, row, ctx, "manual_limit_change", before, req.reason, quota=True)
        await session.commit()
    return {"tenant_id": req.tenant_id, "manual_daily_limit": row.manual_daily_limit,
            "manual_limit_revision": row.manual_limit_revision, "manual_quota": await service.manual_quota(session, req.tenant_id)}


async def history(session, tenant_id, page, page_size, quota):
    where = [Event.tenant_id == tenant_id, (Event.action == "manual_limit_change") if quota else (Event.action != "manual_limit_change")]
    total = await session.scalar(select(func.count()).select_from(Event).where(*where))
    rows = list(await session.scalars(select(Event).where(*where).order_by(Event.id.desc()).offset((page - 1) * page_size).limit(page_size)))
    users = dict((await session.execute(select(User.id, User.display_name).where(User.id.in_([r.actor_user_id for r in rows])))).all())
    return {"total": total, "page": page, "page_size": page_size, "items": [
        {"id": r.id, "tenant_id": r.tenant_id, "actor": {"user_id": r.actor_user_id, "display_name": users.get(r.actor_user_id) or "顾问"},
         "actor_role": r.actor_role, "action": r.action, "created_at": service.iso(r.created_at),
         "before": r.before, "after": r.after, "reason": r.reason, "revision": r.revision} for r in rows]}


@router.get("/visibility-patrol/self-service/history")
async def switch_history(tenant_id: int = Query(..., gt=0), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    await read_access(session, ctx, tenant_id)
    return await history(session, tenant_id, page, page_size, False)


@router.get("/visibility-patrol/manual-limit/history")
async def manual_limit_history(tenant_id: int = Query(..., gt=0), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    service.require_admin(ctx)
    return await history(session, tenant_id, page, page_size, True)


@router.get("/visibility-patrol/admin-settings")
async def admin_settings(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    enabled: bool | None = None, admin_locked: bool | None = None, blocked: bool | None = None,
    search: str | None = Query(None, max_length=100), ctx=Depends(require_scoped_auth), session=Depends(get_session)):
    service.require_admin(ctx)
    query = select(Tenant, Settings).outerjoin(Settings, Settings.tenant_id == Tenant.id)
    if enabled is not None:
        query = query.where(func.coalesce(Settings.self_service_enabled, False) == enabled)
    if admin_locked is not None:
        query = query.where(func.coalesce(Settings.admin_locked, False) == admin_locked)
    if blocked is not None:
        query = query.where(Settings.blocked_reason.is_not(None) if blocked else Settings.blocked_reason.is_(None))
    if search:
        query = query.where(Tenant.name.contains(search, autoescape=True))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await session.execute(query.order_by(Tenant.id).offset((page - 1) * page_size).limit(page_size))).all()
    ids = [t.id for t, _ in rows]
    engines = list(await session.scalars(select(GeoTrackingEngine).where(GeoTrackingEngine.tenant_id.in_(ids))))
    lasts = {r.tenant_id: r for r in await session.scalars(select(Run).where(Run.tenant_id.in_(ids), Run.auto_day.is_not(None))
        .distinct(Run.tenant_id).order_by(Run.tenant_id, Run.id.desc()))}
    inflight = set(await session.scalars(select(Run.tenant_id).where(Run.tenant_id.in_(ids), Run.status.in_(("pending", "running")))))
    start, end = service.day_bounds()
    from app.security.advisor_quota import STATE
    counts = dict((await session.execute(select(Run.tenant_id, func.count()).where(Run.tenant_id.in_(ids),
        Run.created_at >= start, Run.created_at < end, service.manual_condition(),
        func.coalesce(Run.summary[STATE].as_string(), "") != "refunded").group_by(Run.tenant_id))).all())
    user_ids = {ident for _, row in rows if row for ident in (row.owner_user_id, row.opened_by, row.last_changed_by) if ident}
    users = dict((await session.execute(select(User.id, User.display_name).where(User.id.in_(user_ids)))).all())
    items = []
    for tenant, row in rows:
        bundle = ([e for e in engines if e.tenant_id == tenant.id], lasts.get(tenant.id), tenant.id in inflight,
                  {"used": counts.get(tenant.id, 0), "limit": row.manual_daily_limit if row else 10}, users)
        items.append({**await service.state_payload(session, tenant.id, ctx, row=row, bundle=bundle), "tenant_name": tenant.name})
    return {"items": items, "total": total, "page": page, "page_size": page_size}
