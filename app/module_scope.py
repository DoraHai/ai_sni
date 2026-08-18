from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant, TenantModule
if TYPE_CHECKING:
    from app.security.auth import AuthContext


MODULE_CODES = {"sem", "seo", "geo"}
ACTIVE_MODULE_STATUSES = {"active", "trial"}


def normalize_module_code(value: str) -> str:
    code = str(value or "").strip().lower()
    if code not in MODULE_CODES:
        raise HTTPException(400, "模块必须是 sem、seo 或 geo")
    return code


def module_is_available(row: TenantModule) -> bool:
    return row.status in ACTIVE_MODULE_STATUSES and (
        row.expires_at is None or row.expires_at >= date.today()
    )


async def get_tenant_module(
    session: AsyncSession,
    tenant_id: int,
    module_code: str,
    *,
    require_active: bool = True,
) -> TenantModule:
    code = normalize_module_code(module_code)
    row = await session.scalar(
        select(TenantModule).where(
            TenantModule.tenant_id == tenant_id,
            TenantModule.module_code == code,
        )
    )
    if row is None:
        raise HTTPException(403, f"当前客户尚未开通 {code.upper()} 模块")
    if require_active and not module_is_available(row):
        raise HTTPException(403, f"当前客户的 {code.upper()} 模块未启用或已过期")
    return row


async def ensure_module_access(
    session: AsyncSession,
    ctx: "AuthContext",
    tenant_id: int,
    module_code: str,
) -> TenantModule:
    ctx.ensure_tenant(tenant_id)
    return await get_tenant_module(session, tenant_id, module_code)


async def list_module_tenants(
    session: AsyncSession,
    ctx: "AuthContext",
    module_code: str,
) -> list[Tenant]:
    code = normalize_module_code(module_code)
    stmt = (
        select(Tenant)
        .join(TenantModule, TenantModule.tenant_id == Tenant.id)
        .where(
            TenantModule.module_code == code,
            TenantModule.status.in_(ACTIVE_MODULE_STATUSES),
            or_(TenantModule.expires_at.is_(None), TenantModule.expires_at >= date.today()),
        )
        .order_by(Tenant.id)
    )
    if ctx.tenant_id is not None:
        stmt = stmt.where(Tenant.id == ctx.tenant_id)
    rows = list((await session.scalars(stmt)).all())
    return rows
