from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TenantModule

if TYPE_CHECKING:
    from app.security.auth import AuthContext


ACTIVE_MODULE_STATUSES = {"active", "trial"}


def module_is_available(row: TenantModule) -> bool:
    return row.status in ACTIVE_MODULE_STATUSES and (
        row.expires_at is None or row.expires_at >= date.today()
    )


async def ensure_module_access(
    session: AsyncSession,
    ctx: "AuthContext",
    tenant_id: int,
    module_code: str,
) -> TenantModule:
    """Apply the shared tenant binding and active module checks used by workspace assets."""
    ctx.ensure_tenant(tenant_id)
    row = await session.scalar(
        select(TenantModule).where(
            TenantModule.tenant_id == tenant_id,
            TenantModule.module_code == module_code,
        )
    )
    if row is None:
        raise HTTPException(403, f"当前客户尚未开通 {module_code.upper()} 模块")
    if not module_is_available(row):
        raise HTTPException(403, f"当前客户的 {module_code.upper()} 模块未启用或已过期")
    return row
