"""GEO-only tenant entitlement lookup.

This stays inside the independently deployed GEO service so the standalone
workspace does not depend on the SEM backend's version of ``/auth/tenants``.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, String, and_, case, cast, column, func, literal, or_, select, table
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo.demo_tenant import (
    GeoDemoBindingUnavailable,
    GeoTenantPolicy,
    enforce_demo_request,
    policy_from_binding,
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
)

_DEMO_BINDINGS = table(
    "demo_tenant_bindings",
    column("tenant_id", BigInteger),
    column("demo_tenant_id", BigInteger),
    column("dataset_key", String),
    column("dataset_version", String),
    column("status", String),
    column("version", BigInteger),
    schema="public",
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


def ensure_geo_background_execution_allowed(tenant_id: int) -> None:
    """Reject the embedded demo tenant before worker locks, writes or calls."""
    from app.geo.tenant16_demo import is_demo_tenant
    if is_demo_tenant(int(tenant_id)):
        raise GeoEntitlementUnavailable()


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
    if lock_binding:
        # Lock the parent tenant first.  The binding FK prevents a concurrent
        # insert while this transaction is deciding which data source to use.
        # Then lock the current binding row so replace/disable cannot race the
        # selected read or execution path.
        entitled = await session.scalar(
            # Lock only the parent tenant.  Locking every joined row would hold
            # tenant_modules across external work and prevent revocation from
            # committing before the executor's required post-send recheck.
            geo_tenant_entitlement_query(tenant_id).with_for_update(of=Tenant)
        )
        if entitled is None:
            raise GeoEntitlementUnavailable()
        binding = await session.scalar(
            demo_tenant_binding_query(tenant_id).with_for_update()
        )
        binding = binding or {}
    else:
        binding = await session.scalar(
            geo_tenant_policy_query(tenant_id)
        )
        if binding is None:
            raise GeoEntitlementUnavailable()
    try:
        policy = policy_from_binding(tenant_id, binding)
    except GeoDemoBindingUnavailable:
        if allow_demo_read:
            raise
        raise GeoEntitlementUnavailable() from None
    if policy.is_demo and not allow_demo_read:
        raise GeoEntitlementUnavailable()
    return policy


def geo_tenant_entitlement_query(tenant_id: int, *, today: date | None = None):
    """Select one entitled parent tenant; callers may lock it before routing."""
    today = today or date.today()
    return (
        select(Tenant.id)
        .join(_TENANT_MODULES, _TENANT_MODULES.c.tenant_id == Tenant.id)
        .where(
            Tenant.id == tenant_id,
            _TENANT_MODULES.c.module_code == "geo",
            _TENANT_MODULES.c.status.in_(("active", "trial")),
            or_(
                _TENANT_MODULES.c.expires_at.is_(None),
                _TENANT_MODULES.c.expires_at >= today,
            ),
        )
        .limit(1)
    )


def demo_tenant_binding_query(tenant_id: int):
    """Return any 0098 binding so disabled rows cannot fall back to production."""
    return select(
        func.jsonb_build_object(
            "tenant_id", _DEMO_BINDINGS.c.tenant_id,
            "demo_tenant_id", _DEMO_BINDINGS.c.demo_tenant_id,
            "dataset_key", _DEMO_BINDINGS.c.dataset_key,
            "dataset_version", _DEMO_BINDINGS.c.dataset_version,
            "status", _DEMO_BINDINGS.c.status,
            "version", _DEMO_BINDINGS.c.version,
        )
    ).where(_DEMO_BINDINGS.c.tenant_id == tenant_id)


def geo_tenant_policy_query(
    tenant_id: int,
    *,
    today: date | None = None,
):
    """Build a non-locking entitlement plus 0098 binding lookup."""
    today = today or date.today()
    binding_payload = func.jsonb_build_object(
        "tenant_id", _DEMO_BINDINGS.c.tenant_id,
        "demo_tenant_id", _DEMO_BINDINGS.c.demo_tenant_id,
        "dataset_key", _DEMO_BINDINGS.c.dataset_key,
        "dataset_version", _DEMO_BINDINGS.c.dataset_version,
        "status", _DEMO_BINDINGS.c.status,
        "version", _DEMO_BINDINGS.c.version,
    )
    settings_query = (
        select(
            case(
                (_DEMO_BINDINGS.c.tenant_id.is_not(None), binding_payload),
                else_=cast(literal("{}"), JSONB),
            )
        )
        .select_from(Tenant)
        .join(_TENANT_MODULES, _TENANT_MODULES.c.tenant_id == Tenant.id)
        .outerjoin(
            _DEMO_BINDINGS,
            _DEMO_BINDINGS.c.tenant_id == Tenant.id,
        )
        .where(
            Tenant.id == tenant_id,
            _TENANT_MODULES.c.module_code == "geo",
            _TENANT_MODULES.c.status.in_(("active", "trial")),
            or_(
                _TENANT_MODULES.c.expires_at.is_(None),
                _TENANT_MODULES.c.expires_at >= today,
            ),
        )
        .limit(1)
    )
    return settings_query


async def require_geo_read_entitlement(tenant_id: int, ctx=Depends(require_scoped_auth),
                                       session=Depends(get_session)):
    """Check selected-customer entitlement even for a bookmarked ID or admin key.

    Reuse the existing active/trial and inclusive date boundary without changing
    cross-module policy. Database errors propagate (never grant on lookup failure).
    """
    ctx.ensure_tenant(tenant_id)
    from app.geo.tenant16_demo import is_tenant16_demo
    if is_tenant16_demo(ctx, tenant_id):
        return ctx
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
        from app.geo.tenant16_demo import is_tenant16_demo
        if is_tenant16_demo(ctx, tenant_id):
            from app.geo.demo_tenant import GeoDemoExecutionBlocked
            path = request.url.path.rstrip("/") or "/"
            if request.method.upper() in {"GET", "HEAD", "OPTIONS"} and (
                path.startswith("/api/v1/geo/integration/read/")
                or path in {
                    "/api/v1/geo/integration/metrics/snapshot",
                    "/api/v1/geo/integration/metrics/dictionary",
                }
            ):
                continue
            raise GeoDemoExecutionBlocked()
        policy = await ensure_geo_entitlement(
            session, tenant_id, allow_demo_read=True, lock_binding=True
        )
        enforce_demo_request(policy, request)
    return ctx
