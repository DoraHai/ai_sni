import asyncio
from datetime import date
from unittest.mock import AsyncMock, Mock
import pytest
from fastapi import HTTPException
from app.geo.tenant_scope import require_geo_read_entitlement, geo_tenant_query
from app.geo.read_routes import router as read_router
from app.geo.integration import router as integration_router


def test_all_new_reads_and_official_metrics_have_entitlement_dependency():
    routes = list(read_router.routes) + [r for r in integration_router.routes if '/metrics/' in r.path]
    for route in routes:
        assert any(dep.call is require_geo_read_entitlement for dep in route.dependant.dependencies)


def test_unavailable_customer_and_lookup_error_never_grant():
    with pytest.raises(HTTPException) as error:
        asyncio.run(require_geo_read_entitlement(15, Mock(), Mock(scalar=AsyncMock(return_value=None))))
    assert error.value.status_code == 403
    with pytest.raises(RuntimeError):
        asyncio.run(require_geo_read_entitlement(15, Mock(), Mock(scalar=AsyncMock(side_effect=RuntimeError('DB unavailable')))))


def test_bound_customer_checked_before_lookup():
    ctx = Mock(ensure_tenant=Mock(side_effect=HTTPException(403)))
    session = Mock(scalar=AsyncMock())
    with pytest.raises(HTTPException):
        asyncio.run(require_geo_read_entitlement(15, ctx, session))
    session.scalar.assert_not_awaited()


def test_query_reuses_existing_module_status_and_inclusive_expiry():
    sql = str(geo_tenant_query(tenant_id=15, today=date(2026,9,6)).compile(compile_kwargs={'literal_binds': True}))
    for fragment in ["module_code = 'geo'", "'active', 'trial'", "expires_at IS NULL", "expires_at >= '2026-09-06'", 'tenants.id = 15']:
        assert fragment in sql
    ctx = Mock()
    assert asyncio.run(require_geo_read_entitlement(15, ctx, Mock(scalar=AsyncMock(return_value=object())))) is ctx
