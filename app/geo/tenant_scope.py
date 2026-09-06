"""GEO-only tenant entitlement lookup.

This stays inside the independently deployed GEO service so the standalone
workspace does not depend on the SEM backend's version of ``/auth/tenants``.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, String, and_, column, or_, select, table
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant
from fastapi import Depends, HTTPException
from app.database import get_session
from app.security.auth import require_scoped_auth


_TENANT_MODULES = table(
    "tenant_modules",
    column("tenant_id", BigInteger),
    column("module_code", String),
    column("status", String),
    column("expires_at", Date),
)


def geo_tenant_query(*, tenant_id: int | None = None, today: date | None = None):
    """Build the read-only query for customers with an active GEO entitlement."""
    current_date = today or date.today()
    conditions = [
        _TENANT_MODULES.c.module_code == "geo",
        _TENANT_MODULES.c.status.in_(("active", "trial")),
        or_(
            _TENANT_MODULES.c.expires_at.is_(None),
            _TENANT_MODULES.c.expires_at >= current_date,
        ),
    ]
    if tenant_id is not None:
        conditions.append(Tenant.id == tenant_id)
    return (
        select(Tenant)
        .join(_TENANT_MODULES, _TENANT_MODULES.c.tenant_id == Tenant.id)
        .where(and_(*conditions))
        .order_by(Tenant.id)
    )


async def list_geo_tenants(
    session: AsyncSession,
    *,
    tenant_id: int | None = None,
) -> list[Tenant]:
    """Return only tenants whose GEO module is currently usable."""
    return list((await session.scalars(geo_tenant_query(tenant_id=tenant_id))).all())


async def list_geo_tenants_for_auth(
    session: AsyncSession,
    *,
    bound_tenant_id: int | None,
) -> list[Tenant]:
    """Switcher list: unbound accounts see every enabled GEO tenant; bound accounts see only themselves."""
    tenants = await list_geo_tenants(session)
    if bound_tenant_id is None:
        return tenants
    return [tenant for tenant in tenants if tenant.id == bound_tenant_id]


async def require_geo_read_entitlement(tenant_id: int, ctx=Depends(require_scoped_auth),
                                       session=Depends(get_session)):
    """Check selected-customer entitlement even for a bookmarked ID or admin key.

    Reuse the existing active/trial and inclusive date boundary without changing
    cross-module policy. Database errors propagate (never grant on lookup failure).
    """
    ctx.ensure_tenant(tenant_id)
    if await session.scalar(geo_tenant_query(tenant_id=tenant_id).limit(1)) is None:
        raise HTTPException(403, {'code': 'geo_not_available', 'message': '该客户未开通 GEO、已停用或已到期'})
    return ctx
