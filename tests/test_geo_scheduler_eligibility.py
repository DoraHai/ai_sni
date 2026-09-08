import asyncio
import inspect
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.geo.content.geo_scheduler import (
    current_patrol_settings,
    lock_scheduler_tenant,
    run_geo_visibility_patrols,
    scheduled_patrol_settings_query,
)
from app.geo.read_routes import get_scheduler_eligibility, read_session, router
from app.geo.content.routes import (
    put_visibility_patrol_settings,
    router as content_router,
)
from app.geo.content.schemas import SchedulerSafeFoundationRequest
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


def test_scheduler_reloads_settings_after_tenant_lock_and_fails_closed_when_disabled():
    class Context:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_args):
            return False

    scanned = NS(tenant_id=4, enabled=True)
    session = Mock(
        scalars=AsyncMock(return_value=[scanned]),
        commit=AsyncMock(),
    )
    with (
        patch(
            "app.database.async_session_factory",
            return_value=Context(),
        ),
        patch(
            "app.geo.content.geo_scheduler.lock_scheduler_tenant",
            AsyncMock(return_value=True),
        ) as lock,
        patch(
            "app.geo.content.geo_scheduler.current_patrol_settings",
            AsyncMock(return_value=NS(tenant_id=4, enabled=False)),
        ) as reload_settings,
        patch(
            "app.geo.content.patrol.execute_patrol_run_owned",
            AsyncMock(side_effect=AssertionError("patrol execution is forbidden")),
        ),
    ):
        asyncio.run(run_geo_visibility_patrols())

    lock.assert_awaited_once_with(session, 4)
    reload_settings.assert_awaited_once_with(session, 4)
    session.add.assert_not_called()
    session.commit.assert_awaited_once()


def test_shared_lock_and_current_settings_queries_are_tenant_scoped():
    session = Mock(scalar=AsyncMock(side_effect=[4, NS(tenant_id=4, enabled=False)]))

    assert asyncio.run(lock_scheduler_tenant(session, 4)) is True
    current = asyncio.run(current_patrol_settings(session, 4))

    assert current.enabled is False
    queries = [
        str(call.args[0].compile(compile_kwargs={"literal_binds": True}))
        for call in session.scalar.await_args_list
    ]
    assert "tenants.id = 4" in queries[0]
    assert "FOR UPDATE" in queries[0]
    assert "geo_visibility_patrol_settings.tenant_id = 4" in queries[1]


def test_settings_write_and_atomic_foundation_share_scheduler_tenant_lock():
    settings_source = inspect.getsource(put_visibility_patrol_settings)
    scheduler_source = inspect.getsource(run_geo_visibility_patrols)
    foundation_route = next(
        route
        for route in content_router.routes
        if route.path == "/integration/scheduler-safe-foundation"
    )

    assert "lock_scheduler_tenant" in settings_source
    assert "current_patrol_settings" in settings_source
    assert "lock_scheduler_tenant" in scheduler_source
    assert "current_patrol_settings" in scheduler_source
    assert foundation_route.methods == {"POST"}
    assert any(
        dep.call is require_geo_read_entitlement
        for dep in foundation_route.dependant.dependencies
    )
    assert _required(
        "/api/v1/geo/integration/scheduler-safe-foundation", "POST"
    ) == ({"geo.content"}, True)


@pytest.mark.parametrize(
    "channel_patch",
    [
        {"enabled": True},
        {"publish_mode": "auto_publish"},
        {"publish_mode": "draft_then_manual"},
    ],
)
def test_atomic_foundation_schema_rejects_collecting_or_publishing_channel(channel_patch):
    payload = {
        "tenant_id": 4,
        "business": {"name": "Safe business"},
        "prompts": [{"question": "How should this product be selected?"}],
        "channel": {
            "name": "Safe website",
            "channel_type": "website",
            "enabled": False,
            "publish_mode": "manual_only",
            **channel_patch,
        },
    }

    with pytest.raises(ValidationError):
        SchedulerSafeFoundationRequest.model_validate(payload)
