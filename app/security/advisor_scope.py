"""Shared SEM/SEO advisor predicate and per-request, fail-closed grant reads."""
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.models.advisor_tenant_grant import AdvisorTenantGrant
from app.models.tenant import Tenant
from app.permissions import effective_role_permissions


def deny(status: int, code: str, message: str) -> None:
    raise HTTPException(status, {"code": code, "message": message})


def is_advisor(role) -> bool:
    """Identity only: activation, lock and default tenant are separate gates."""
    if role is None or (role.is_system and role.name == "管理员"):
        return False
    perms = effective_role_permissions(role.name, role.is_system, role.permissions)
    return (not any(k.startswith("settings.") and v == "edit" for k, v in perms.items())
            and ((perms.get("seo.site") == "edit" and perms.get("seo.content") == "edit")
                 or (perms.get("geo.assets") == "edit" and perms.get("geo.content") == "edit")))


def account_locked(user) -> bool:
    until = user.locked_until
    if until is None:
        return False
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return until > datetime.now(timezone.utc)


@dataclass(frozen=True)
class AdvisorScope:
    """Explicitly restricted, including when no current customer is selected."""
    tenant_ids: frozenset[int]
    tenant_id: int | None = None
    grant_id: int | None = None

    def ensure_tenant(self, tenant_id):
        if not self.tenant_ids:
            deny(403, "ADVISOR_NO_TENANT", "顾问尚未获准访问任何客户")
        if self.tenant_id is None or self.grant_id is None:
            deny(409, "ADVISOR_TENANT_SELECTION_REQUIRED", "请先切换客户")
        if type(tenant_id) is not int or tenant_id != self.tenant_id or tenant_id not in self.tenant_ids:
            deny(403, "ADVISOR_TENANT_NOT_GRANTED", "无权访问当前会话以外的客户")


async def read_grants(session, user_id):
    """No cross-request cache; include revoked rows as a restriction marker.

    SAVEPOINT keeps a missing-table error from poisoning a non-advisor's
    existing transaction. No connection configuration is read here.
    """
    try:
        async with session.begin_nested():
            return list((await session.scalars(select(AdvisorTenantGrant).where(
                AdvisorTenantGrant.user_id == user_id
            ).execution_options(populate_existing=True))).all())
    except DBAPIError:
        deny(503, "ADVISOR_GRANTS_UNAVAILABLE", "顾问客户授权尚未就绪")


async def active_grants(session, rows):
    active = [g for g in rows if g.revoked_at is None]
    if not active:
        return []
    existing = set((await session.scalars(select(Tenant.id).where(
        Tenant.id.in_([g.tenant_id for g in active])
    ))).all())
    return [g for g in active if g.tenant_id in existing]
