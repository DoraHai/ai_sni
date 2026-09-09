import asyncio
from contextlib import asynccontextmanager
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.geo.demo_tenant import (
    DEMO_DATASET_KEY,
    DEMO_FIXTURE_NAMESPACE,
    GeoDemoBindingUnavailable,
    demo_metric_rows,
    enforce_demo_request,
    policy_from_binding,
)
from app.geo.tenant_scope import (
    demo_tenant_binding_query,
    GeoEntitlementUnavailable,
    ensure_geo_entitlement,
    geo_tenant_entitlement_query,
    geo_tenant_policy_query,
)


def _request(method: str, path: str) -> Request:
    return Request({
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "scheme": "https",
        "server": ("gsnipers.snipers.com.cn", 443),
    })


def _demo_binding():
    return {
        "tenant_id": 8,
        "demo_tenant_id": 108,
        "dataset_key": DEMO_DATASET_KEY,
        "dataset_version": "demo-20260909-v1",
        "status": "active",
        "version": 1,
    }


def test_policy_uses_only_exact_server_binding_and_never_client_hints():
    production = policy_from_binding(7, {})
    assert not production.is_demo and not production.read_only

    demo = policy_from_binding(8, _demo_binding())
    assert demo.is_demo and demo.read_only
    assert demo.dataset_key == "gsnipers_demo"
    assert demo.demo_tenant_id == 108

    for invalid in (
        None,
        {**_demo_binding(), "tenant_id": 9},
        {**_demo_binding(), "demo_tenant_id": 0},
        {**_demo_binding(), "dataset_key": "sem_prod"},
        {**_demo_binding(), "status": "disabled"},
        {**_demo_binding(), "extra": True},
    ):
        with pytest.raises(GeoDemoBindingUnavailable):
            policy_from_binding(8, invalid)


def test_entitlement_lookup_uses_0098_binding_without_hiding_disabled_rows():
    sql = str(
        geo_tenant_policy_query(8, today=date(2026, 9, 9)).compile(
            compile_kwargs={"literal_binds": True}
        )
    )
    assert "public.demo_tenant_bindings" in sql
    assert "demo_tenant_bindings.status = 'active'" not in sql
    assert "tenant_modules.module_code = 'geo'" in sql
    assert "tenant_modules.expires_at >= '2026-09-09'" in sql
    assert "FOR UPDATE" not in sql

    entitlement_sql = str(
        geo_tenant_entitlement_query(8, today=date(2026, 9, 9))
        .with_for_update()
        .compile(compile_kwargs={"literal_binds": True})
    )
    binding_sql = str(
        demo_tenant_binding_query(8)
        .with_for_update()
        .compile(compile_kwargs={"literal_binds": True})
    )
    assert "FROM tenants JOIN tenant_modules" in entitlement_sql
    assert "FOR UPDATE" in entitlement_sql
    assert "FROM public.demo_tenant_bindings" in binding_sql
    assert "demo_tenant_bindings.status = 'active'" not in binding_sql
    assert "FOR UPDATE" in binding_sql


def test_demo_policy_allows_only_null_metric_contract_without_data_source_fallback():
    policy = policy_from_binding(8, _demo_binding())
    enforce_demo_request(policy, _request("GET", "/api/v1/geo/integration/metrics/snapshot"))
    enforce_demo_request(policy, _request("GET", "/api/v1/geo/integration/metrics/dictionary"))

    enforce_demo_request(policy, _request("GET", "/api/v1/geo/integration/read/answers"))
    with pytest.raises(HTTPException) as exc:
        enforce_demo_request(policy, _request("POST", "/api/v1/geo/integration/tasks"))
    assert exc.value.status_code == 403


def test_demo_formal_metrics_are_always_null():
    rows = demo_metric_rows(as_of="2026-09-07T00:00:00+08:00")
    assert len(rows) == 3
    assert all(row["value"] is None and row["trend_7d"] is None for row in rows)
    assert {row["metric_key"] for row in rows} == {
        "geo.visibility.ai_mention_count_7d",
        "geo.visibility.ai_visibility_score",
        "geo.visibility.ai_mention_rate_7d",
    }


def test_demo_database_target_is_fixed_and_cannot_equal_primary():
    from app.geo.demo_read_session import resolve_demo_database_target

    policy = policy_from_binding(8, _demo_binding())
    env = {
        "GEO_DEMO_DATASET_KEY": "gsnipers_demo",
        "GEO_DEMO_DATASET_VERSION": "demo-20260909-v1",
        "GEO_DEMO_DATABASE_URL": "postgresql+asyncpg://geo_demo_read:secret@db-demo.internal/gsnipers_demo",
        "GEO_DEMO_DATABASE_NAME": "gsnipers_demo",
        "GEO_DEMO_DATABASE_USER": "geo_demo_read",
        "GEO_DEMO_DATABASE_HOST_ALLOWLIST": "db-demo.internal",
        "GEO_DEMO_DATABASE_SERVER_ADDR_ALLOWLIST": "10.0.0.8",
        "GEO_DEMO_SCHEMA_REVISION": "0098_demo_binding_no_truncate",
    }
    with patch(
        "app.geo.demo_read_session.get_settings",
        return_value=SimpleNamespace(
            database_url="postgresql+asyncpg://prod:secret@db.internal/sem_prod"
        ),
    ):
        target = resolve_demo_database_target(policy, env)
    assert target.database == "gsnipers_demo"
    assert target.username == "geo_demo_read"
    assert target.server_addresses == frozenset({"10.0.0.8"})

    bad = {**env, "GEO_DEMO_DATABASE_URL": env["GEO_DEMO_DATABASE_URL"].replace(
        "db-demo.internal/gsnipers_demo", "db.internal/sem_prod"
    ), "GEO_DEMO_DATABASE_NAME": "sem_prod", "GEO_DEMO_DATABASE_HOST_ALLOWLIST": "db.internal"}
    with patch(
        "app.geo.demo_read_session.get_settings",
        return_value=SimpleNamespace(
            database_url="postgresql+asyncpg://prod:secret@db.internal/sem_prod"
        ),
    ), pytest.raises(GeoDemoBindingUnavailable):
        resolve_demo_database_target(policy, bad)


def test_internal_execution_guard_rechecks_trusted_binding():
    session = Mock(scalar=AsyncMock(return_value=_demo_binding()))
    with pytest.raises(GeoEntitlementUnavailable):
        asyncio.run(ensure_geo_entitlement(session, 8))

    policy = asyncio.run(ensure_geo_entitlement(session, 8, allow_demo_read=True))
    assert policy.is_demo

    disabled = Mock(
        scalar=AsyncMock(return_value={**_demo_binding(), "status": "disabled"})
    )
    with pytest.raises(GeoDemoBindingUnavailable):
        asyncio.run(ensure_geo_entitlement(disabled, 8, allow_demo_read=True))


def test_missing_entitlement_and_malformed_binding_fail_closed():
    missing = Mock(scalar=AsyncMock(return_value=None))
    with pytest.raises(GeoEntitlementUnavailable):
        asyncio.run(ensure_geo_entitlement(missing, 8))

    malformed = Mock(scalar=AsyncMock(return_value={"tenant_id": 8, "status": "active"}))
    with pytest.raises(GeoDemoBindingUnavailable):
        asyncio.run(ensure_geo_entitlement(malformed, 8, allow_demo_read=True))

    with pytest.raises(GeoEntitlementUnavailable):
        asyncio.run(ensure_geo_entitlement(malformed, 8))


def test_demo_snapshot_returns_null_without_querying_production_metrics():
    from app.geo.integration import metrics_snapshot

    session = Mock(scalar=AsyncMock(return_value=_demo_binding()), commit=AsyncMock())
    ctx = Mock()
    with patch("app.geo.integration.snapshot", AsyncMock()) as load:
        result = asyncio.run(metrics_snapshot(8, None, ctx, session))
    assert all(row["value"] is None and row["trend_7d"] is None for row in result)
    load.assert_not_awaited()
    session.commit.assert_not_awaited()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(metrics_snapshot(8, date(2026, 9, 8), ctx, session))
    assert exc.value.status_code == 400


def test_demo_oauth_callback_stops_before_account_or_network_access():
    from app.geo.content.oauth_public import oauth_social_callback

    session = Mock(
        scalar=AsyncMock(return_value=_demo_binding()),
        get=AsyncMock(),
        commit=AsyncMock(),
    )
    with patch(
        "app.geo.content.connectors.oauth2.parse_oauth_state",
        return_value={"tenant_id": 8, "account_id": 4},
    ), patch(
        "app.geo.content.connectors.oauth2.exchange_code_for_tokens", AsyncMock()
    ) as exchange:
        with pytest.raises(GeoEntitlementUnavailable):
            asyncio.run(oauth_social_callback("code", "signed-state", session))
    session.get.assert_not_awaited()
    session.commit.assert_not_awaited()
    exchange.assert_not_awaited()


def test_existing_public_share_stops_after_tenant_is_rebound_to_demo():
    from app.geo.content.oauth_public import get_deliverable_by_share_token

    archive = SimpleNamespace(tenant_id=8)
    session = Mock(
        scalar=AsyncMock(side_effect=[archive, _demo_binding(), _demo_binding()]),
        commit=AsyncMock(),
    )
    with pytest.raises(GeoEntitlementUnavailable):
        asyncio.run(get_deliverable_by_share_token("old-production-share", session))
    session.commit.assert_not_awaited()


def test_demo_worker_stops_before_claim_write_or_model_execution():
    from app.geo.content import async_jobs

    row = SimpleNamespace(id=42, tenant_id=8, status="pending")
    session = SimpleNamespace(
        get=AsyncMock(return_value=row),
        scalar=AsyncMock(return_value=_demo_binding()),
        rollback=AsyncMock(),
        commit=AsyncMock(),
    )

    @asynccontextmanager
    async def factory(**_kwargs):
        yield session

    with patch("app.database.async_session_factory", factory), patch.object(
        async_jobs, "_execute_generate", AsyncMock()
    ) as execute:
        result = asyncio.run(async_jobs._run_owned_job(42))
    assert result["status"] == "blocked"
    assert session.scalar.await_count == 2
    session.commit.assert_not_awaited()
    execute.assert_not_awaited()
