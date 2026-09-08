import asyncio
import inspect
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException

from app.geo.content.geo_scheduler import (
    run_geo_visibility_patrols,
    scheduled_patrol_settings_query,
)
from app.geo.read_routes import get_scheduler_eligibility, read_session, router
from app.geo.tenant_scope import require_geo_read_entitlement
from app.security.auth import _required


def _route():
    return next(
        route
        for route in router.routes
        if route.path == "/integration/read/scheduler-eligibility"
    )


def test_route_is_get_only_tenant_scoped_and_requires_geo_content():
    route = _route()

    assert route.methods == {"GET"}
    assert any(dep.call is read_session for dep in route.dependant.dependencies)
    assert any(
        dep.call is require_geo_read_entitlement for dep in route.dependant.dependencies
    )
    assert _required(
        "/api/v1/geo/integration/read/scheduler-eligibility", "GET"
    ) == ({"geo.content"}, False)


def test_endpoint_reuses_scheduler_selection_query_and_returns_no_settings_secrets():
    settings = NS(enabled=True, engine_keys=["private-engine"], prefer_real=True)
    session = Mock(
        scalar=AsyncMock(side_effect=[settings, settings, 3]),
    )
    ctx = Mock()

    result = asyncio.run(get_scheduler_eligibility(4, ctx, session))

    ctx.ensure_tenant.assert_called_once_with(4)
    assert result["tenant_id"] == 4
    assert result["read_only"] is True
    assert result["patrol_settings"] == {"exists": True, "enabled": True}
    assert result["active_prompt_count"] == 3
    assert result["scheduler_eligible"] is True
    assert result["selection_stage"] == "enabled_settings_scan"
    assert result["run_creation_guaranteed"] is False
    assert result["observed_at"].endswith("Z")
    assert "private-engine" not in str(result)
    assert "engine_keys" not in result
    assert "prefer_real" not in result

    queries = [
        str(call.args[0].compile(compile_kwargs={"literal_binds": True}))
        for call in session.scalar.await_args_list
    ]
    assert "geo_visibility_patrol_settings.tenant_id = 4" in queries[0]
    assert "geo_visibility_patrol_settings.enabled IS true" in queries[1]
    assert "geo_visibility_patrol_settings.tenant_id = 4" in queries[1]
    assert "geo_prompts.tenant_id = 4" in queries[2]
    assert "geo_prompts.status = 'active'" in queries[2]
    session.add.assert_not_called()
    session.commit.assert_not_called()
    session.flush.assert_not_called()


def test_absent_settings_is_not_initialized_and_is_not_scheduler_eligible():
    session = Mock(scalar=AsyncMock(side_effect=[None, None, 0]))

    result = asyncio.run(get_scheduler_eligibility(4, Mock(), session))

    assert result["patrol_settings"] == {"exists": False, "enabled": False}
    assert result["active_prompt_count"] == 0
    assert result["scheduler_eligible"] is False
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_tenant_scope_failure_stops_before_any_data_query():
    ctx = Mock(ensure_tenant=Mock(side_effect=HTTPException(403)))
    session = Mock(scalar=AsyncMock())

    with pytest.raises(HTTPException):
        asyncio.run(get_scheduler_eligibility(5, ctx, session))

    session.scalar.assert_not_awaited()


def test_runtime_and_endpoint_share_the_exact_enabled_settings_selector():
    sql = str(
        scheduled_patrol_settings_query(tenant_id=4).compile(
            compile_kwargs={"literal_binds": True}
        )
    )

    assert "geo_visibility_patrol_settings.enabled IS true" in sql
    assert "geo_visibility_patrol_settings.tenant_id = 4" in sql
    assert "scheduled_patrol_settings_query()" in inspect.getsource(
        run_geo_visibility_patrols
    )
