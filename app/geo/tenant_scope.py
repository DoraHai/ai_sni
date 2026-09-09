"""GEO-only tenant entitlement lookup.

This stays inside the independently deployed GEO service so the standalone
workspace does not depend on the SEM backend's version of ``/auth/tenants``.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, String, and_, cast, column, func, literal, or_, select, table
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo.demo_tenant import (
    GeoDemoBindingUnavailable,
    GeoTenantPolicy,
    enforce_demo_request,
    policy_from_module_settings,
)
from app.models import Tenant
from fastapi import Depends, HTTPException, Request
from app.database import get_session
from app.security.auth import require_scoped_auth


_TENANT_MODULES = table(
    "tenant_modules",
    column("tenant_id", BigInteger),
    column("module_code", String),
    column("status", String),
    column("expires_at", Date),
    column("module_settings", JSONB),
)


class GeoEntitlementUnavailable(HTTPException):
    """Stable signal for workers that must stop after GEO access is revoked."""

    def __init__(self) -> None:
        super().__init__(
            403,
            {
                "code": "geo_not_available",
                "message": "该客户未开通 GEO、已停用或已到期",
            },
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


async def ensure_geo_entitlement(
    session: AsyncSession,
    tenant_id: int,
    *,
    allow_demo_read: bool = False,
    lock_binding: bool = True,
) -> GeoTenantPolicy:
    """Fail closed unless the customer currently has usable GEO access."""
    settings_query = (
        select(func.coalesce(_TENANT_MODULES.c.module_settings, cast(literal("{}"), JSONB)))
        .select_from(Tenant)
        .join(_TENANT_MODULES, _TENANT_MODULES.c.tenant_id == Tenant.id)
        .where(
            Tenant.id == tenant_id,
            _TENANT_MODULES.c.module_code == "geo",
            _TENANT_MODULES.c.status.in_(("active", "trial")),
            or_(
                _TENANT_MODULES.c.expires_at.is_(None),
                _TENANT_MODULES.c.expires_at >= date.today(),
            ),
        )
        .limit(1)
    )
    if lock_binding:
        settings_query = settings_query.with_for_update()
    module_settings = await session.scalar(settings_query)
    if module_settings is None:
        raise GeoEntitlementUnavailable()
    try:
        policy = policy_from_module_settings(tenant_id, module_settings)
    except GeoDemoBindingUnavailable:
        if allow_demo_read:
            raise
        raise GeoEntitlementUnavailable() from None
    if policy.is_demo and not allow_demo_read:
        raise GeoEntitlementUnavailable()
    return policy


async def require_geo_read_entitlement(tenant_id: int, ctx=Depends(require_scoped_auth),
                                       session=Depends(get_session)):
    """Check selected-customer entitlement even for a bookmarked ID or admin key.

    Reuse the existing active/trial and inclusive date boundary without changing
    cross-module policy. Database errors propagate (never grant on lookup failure).
    """
    ctx.ensure_tenant(tenant_id)
    await ensure_geo_entitlement(
        session, tenant_id, allow_demo_read=True, lock_binding=False
    )
    return ctx


async def require_geo_request_entitlement(
    request: Request,
    ctx=Depends(require_scoped_auth),
    session=Depends(get_session),
):
    """Enforce GEO entitlement whenever a GEO request names a customer.

    GEO routes use both query parameters and JSON request models for
    ``tenant_id``.  Reading JSON through Starlette's cached request body keeps
    normal FastAPI model parsing intact.  Routes without a customer context
    (for example the brief catalog and the already-filtered tenant switcher)
    remain available after authentication.
    """
    candidates = list(request.query_params.getlist("tenant_id"))
    content_type = (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    )
    # Starlette/FastAPI also attempts JSON model parsing when Content-Type is
    # absent.  Match that behavior so omitting the header cannot bypass the
    # tenant carried in an otherwise valid JSON body.
    is_json = not content_type or content_type == "application/json" or (
        content_type.startswith("application/") and content_type.endswith("+json")
    )
    if is_json:
        try:
            payload = await request.json()
        except (ValueError, UnicodeDecodeError):
            payload = None
        if isinstance(payload, dict) and payload.get("tenant_id") is not None:
            candidates.append(payload["tenant_id"])

    tenant_ids: list[int] = []
    for value in candidates:
        try:
            tenant_id = int(value)
        except (TypeError, ValueError):
            continue
        if tenant_id > 0 and tenant_id not in tenant_ids:
            tenant_ids.append(tenant_id)

    for tenant_id in tenant_ids:
        ctx.ensure_tenant(tenant_id)
        policy = await ensure_geo_entitlement(
            session, tenant_id, allow_demo_read=True, lock_binding=True
        )
        enforce_demo_request(policy, request)
    return ctx
