import asyncio
from contextlib import asynccontextmanager
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.geo.demo_tenant import (
    DEMO_FIXTURE_NAMESPACE,
    GeoDemoBindingUnavailable,
    demo_metric_rows,
    enforce_demo_request,
    policy_from_module_settings,
)
from app.geo.tenant_scope import GeoEntitlementUnavailable, ensure_geo_entitlement


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


def _demo_settings():
    return {
        "geo_data_source": {
            "kind": "isolated_demo",
            "database_key": "gsnipers_demo",
            "fixture_namespace": DEMO_FIXTURE_NAMESPACE,
            "read_only": True,
        }
    }


def test_policy_uses_only_exact_server_binding_and_never_client_hints():
    production = policy_from_module_settings(7, {})
    assert not production.is_demo and not production.read_only

    demo = policy_from_module_settings(8, _demo_settings())
    assert demo.is_demo and demo.read_only
    assert demo.database_key == "gsnipers_demo"

    for invalid in (
        None,
        {"geo_data_source": "isolated_demo"},
        {"geo_data_source": {**_demo_settings()["geo_data_source"], "read_only": False}},
        {"geo_data_source": {**_demo_settings()["geo_data_source"], "database_key": "sem_prod"}},
        {"geo_data_source": {**_demo_settings()["geo_data_source"], "extra": True}},
    ):
        with pytest.raises(GeoDemoBindingUnavailable):
            policy_from_module_settings(8, invalid)


def test_demo_policy_allows_only_null_metric_contract_without_data_source_fallback():
    policy = policy_from_module_settings(8, _demo_settings())
    enforce_demo_request(policy, _request("GET", "/api/v1/geo/integration/metrics/snapshot"))
    enforce_demo_request(policy, _request("GET", "/api/v1/geo/integration/metrics/dictionary"))

    with pytest.raises(GeoDemoBindingUnavailable):
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


def test_internal_execution_guard_rechecks_trusted_binding():
    session = Mock(scalar=AsyncMock(return_value=_demo_settings()))
    with pytest.raises(GeoEntitlementUnavailable):
        asyncio.run(ensure_geo_entitlement(session, 8))

    policy = asyncio.run(ensure_geo_entitlement(session, 8, allow_demo_read=True))
    assert policy.is_demo


def test_missing_entitlement_and_malformed_binding_fail_closed():
    missing = Mock(scalar=AsyncMock(return_value=None))
    with pytest.raises(GeoEntitlementUnavailable):
        asyncio.run(ensure_geo_entitlement(missing, 8))

    malformed = Mock(scalar=AsyncMock(return_value={"geo_data_source": {"kind": "production"}}))
    with pytest.raises(GeoDemoBindingUnavailable):
        asyncio.run(ensure_geo_entitlement(malformed, 8, allow_demo_read=True))

    with pytest.raises(GeoEntitlementUnavailable):
        asyncio.run(ensure_geo_entitlement(malformed, 8))


def test_demo_snapshot_returns_null_without_querying_production_metrics():
    from app.geo.integration import metrics_snapshot

    session = Mock(scalar=AsyncMock(return_value=_demo_settings()), commit=AsyncMock())
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
        scalar=AsyncMock(return_value=_demo_settings()),
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
        scalar=AsyncMock(side_effect=[archive, _demo_settings()]),
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
        scalar=AsyncMock(return_value=_demo_settings()),
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
    assert session.scalar.await_count == 1
    session.commit.assert_not_awaited()
    execute.assert_not_awaited()
