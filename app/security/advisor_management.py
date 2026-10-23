"""Advisor administration without schema changes or additional DB privileges."""
import hashlib
from datetime import datetime, timezone
from typing import Annotated

from pydantic import Field
from sqlalchemy import bindparam, select, text
from sqlalchemy.exc import DBAPIError

from app.models import Role, Tenant, TenantModule, User
from app.models.advisor_tenant_grant import AdvisorTenantGrant
from app.module_scope import module_is_available
from app.permissions import PLATFORM_ADMIN_KEYS, effective_role_permissions
from app.security.advisor_scope import account_locked, deny, read_grants

TenantId = Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]


def grants_version(default_tenant_id, rows):
    ids = sorted(str(g.id) for g in rows if g.revoked_at is None)
    value = "v1|" + str(default_tenant_id or "") + "|" + ",".join(ids)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


async def lock_named_admin(session, ctx, target_id=None):
    """Lock actor/target in ID order and recheck the named actor from the DB."""
    if ctx.user_id is None:
        deny(403, "ADVISOR_NAMED_ADMIN_REQUIRED", "需要实名平台账号管理员")
    ids = {ctx.user_id}
    if target_id is not None:
        ids.add(target_id)
    locked = list((await session.scalars(select(User).where(User.id.in_(ids))
        .order_by(User.id).with_for_update().execution_options(populate_existing=True))).all())
    actor = next((u for u in locked if u.id == ctx.user_id), None)
    role = await session.get(Role, actor.role_id, populate_existing=True) if actor else None
    perms = effective_role_permissions(role.name, role.is_system, role.permissions) if role else {}
    if (not actor or not actor.is_active or account_locked(actor)
            or actor.tenant_id is not None
            or not all(perms.get(key) == "edit" for key in PLATFORM_ADMIN_KEYS)):
        deny(403, "ADVISOR_NAMED_ADMIN_REQUIRED", "需要未绑定客户的实名超级管理员")
    return next((u for u in locked if u.id == target_id), None)


async def validate_tenants(session, ids, default_id, role):
    ids = list(dict.fromkeys(ids))
    if not ids:
        deny(422, "ADVISOR_TENANTS_REQUIRED", "至少勾选 1 个客户")
    if default_id not in ids:
        deny(422, "ADVISOR_DEFAULT_TENANT_INVALID", "默认客户必须在勾选的客户中")
    found = set((await session.scalars(select(Tenant.id).where(Tenant.id.in_(ids)))).all())
    if found != set(ids):
        deny(422, "ADVISOR_TENANT_NOT_FOUND", "勾选的客户不存在")
    from app.api.auth import _MODULE_PERMISSION_KEYS
    perms = effective_role_permissions(role.name, role.is_system, role.permissions)
    modules = list((await session.scalars(select(TenantModule).where(TenantModule.tenant_id.in_(ids)))).all())
    usable = {m.tenant_id for m in modules if module_is_available(m) and any(
        perms.get(k) in ("view", "edit") for k in _MODULE_PERMISSION_KEYS.get(m.module_code, ()))}
    if usable != set(ids):
        deny(422, "ADVISOR_TENANT_MODULE_UNAVAILABLE", "勾选客户没有当前角色可用的模块")
    return ids


async def save_grants(session, user, ids, default_id, actor_id, rows):
    """Caller holds users row; never resurrect, delete or mutate grant identity."""
    try:
        return await _save_grants(session, user, ids, default_id, actor_id, rows)
    except DBAPIError:
        await session.rollback()
        deny(503, "ADVISOR_GRANTS_UNAVAILABLE", "顾问客户授权尚未就绪，变更未保存")


async def _save_grants(session, user, ids, default_id, actor_id, rows):
    active = {g.tenant_id: g for g in rows if g.revoked_at is None}
    now = datetime.now(timezone.utc)
    for tid, grant in active.items():
        if tid not in ids:
            grant.revoked_at = now
            grant.revoked_by = actor_id
            grant.revoke_reason = "admin_uncheck"
    for tid in ids:
        if tid not in active:
            session.add(AdvisorTenantGrant(user_id=user.id, tenant_id=tid,
                granted_by=actor_id, grant_source="admin", granted_at=now))
    user.tenant_id = default_id
    await session.flush()
    await _sync_seo_assignments(session, user.id,
        added=set(ids) - active.keys(), removed=active.keys() - set(ids),
        actor_id=actor_id, now=now.replace(tzinfo=None))
    return await read_grants(session, user.id)


async def _sync_seo_assignments(session, user_id, *, added, removed, actor_id, now):
    """Same caller transaction; existing grants are deliberately not backfilled.

    SEM and SEO use the same DATABASE_URL and public tables. SEM has no SEO
    assignment ORM, so use the existing 0105 table without a schema change.
    """
    if removed:
        await session.execute(text("""
            UPDATE seo_site_advisor_assignments
            SET active = false, assigned_by = :actor_id, updated_at = :now
            WHERE advisor_user_id = :user_id AND tenant_id IN :tenant_ids
        """).bindparams(bindparam("tenant_ids", expanding=True)),
            {"tenant_ids": sorted(removed), "actor_id": actor_id, "user_id": user_id, "now": now})
    if added:
        await session.execute(text("""
            INSERT INTO seo_site_advisor_assignments
                (tenant_id, site_id, advisor_user_id, active, assigned_by)
            SELECT tenant_id, id, :user_id, true, :actor_id
            FROM seo_sites WHERE tenant_id IN :tenant_ids AND status = 'active'
            ON CONFLICT (tenant_id, site_id, advisor_user_id) DO UPDATE
            SET active = true, assigned_by = :actor_id, updated_at = :now
        """).bindparams(bindparam("tenant_ids", expanding=True)),
            {"tenant_ids": sorted(added), "actor_id": actor_id, "user_id": user_id, "now": now})
