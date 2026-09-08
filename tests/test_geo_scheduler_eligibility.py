import asyncio
import inspect
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.database import get_session
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
from app.security.auth import AuthContext, _required, require_scoped_auth


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
    assert not any(
        dep.call is require_geo_read_entitlement
        for dep in foundation_route.dependant.dependencies
    )
    assert _required(
        "/api/v1/geo/integration/scheduler-safe-foundation", "POST"
    ) == ({"geo.content"}, True)


def _runbook_foundation_payload():
    return {
        "tenant_id": 4,
        "business": {
            "name": "粉末涂料与表面技术",
            "description": "TIGER/老虎的粉末涂料与表面技术业务画像",
            "sort_order": 0,
            "profile": {
                "product_name": "TIGER/老虎",
                "website": "https://www.tiger-coatings.cn/",
                "summary": "TIGER/老虎粉末涂料与表面技术",
                "industry": "粉末涂料与表面技术",
            },
        },
        "prompts": [
            {
                "question": "在建筑幕墙和系统门窗中选择粉末涂料时，最关键的性能指标和验收标准有哪些？",
                "priority": 0,
                "tags": ["cockpit-foundation"],
                "source": "manual",
                "language": "zh-CN",
                "market": "cn",
                "is_brand_probe": False,
            },
            {
                "question": "粉末涂料与常见液体涂料相比，在成本、寿命、施工和环保方面有什么差异？",
                "priority": 0,
                "tags": ["cockpit-foundation"],
                "source": "manual",
                "language": "zh-CN",
                "market": "cn",
                "is_brand_probe": False,
            },
            {
                "question": "汽车轮毂、家具家电或机器设备出现涂层失效时，常见原因、排查步骤和选型建议是什么？",
                "priority": 0,
                "tags": ["cockpit-foundation"],
                "source": "manual",
                "language": "zh-CN",
                "market": "cn",
                "is_brand_probe": False,
            },
        ],
        "channel": {
            "name": "TIGER 官方网站",
            "channel_type": "website",
            "publish_mode": "manual_only",
            "base_url": "https://www.tiger-coatings.cn/",
            "content_rules": None,
            "enabled": False,
            "sort_order": 0,
        },
    }


def _foundation_http(ctx):
    app = FastAPI()
    app.include_router(content_router, prefix="/api/v1/geo")
    next_id = iter(range(101, 110))
    session = Mock(
        scalar=AsyncMock(side_effect=[NS(id=4), None]),
        scalars=AsyncMock(return_value=[]),
        get=AsyncMock(return_value=NS(id=4, name="Tiger")),
        flush=AsyncMock(),
        commit=AsyncMock(),
    )

    def add(row):
        if getattr(row, "id", None) is None:
            row.id = next(next_id)

    session.add = Mock(side_effect=add)
    app.dependency_overrides[require_scoped_auth] = lambda: ctx
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app), session


def test_runbook_body_only_http_request_reaches_atomic_handler_without_query_tenant():
    ctx = AuthContext(
        user_id=9,
        username="tiger_operator",
        role_name="tenant-editor",
        tenant_id=4,
        permissions={"geo.content": "edit"},
    )
    http, session = _foundation_http(ctx)

    with (
        patch(
            "app.geo.content.geo_scheduler.lock_scheduler_tenant",
            AsyncMock(return_value=True),
        ),
        patch(
            "app.geo.content.geo_scheduler.current_patrol_settings",
            AsyncMock(return_value=NS(enabled=False)),
        ),
    ):
        response = http.post(
            "/api/v1/geo/integration/scheduler-safe-foundation",
            json=_runbook_foundation_payload(),
        )

    assert response.status_code == 200, response.text
    assert response.json()["tenant_id"] == 4
    assert response.json()["atomic"] is True
    assert len(response.json()["decisions"]["prompts"]) == 3
    session.commit.assert_awaited_once()


@pytest.mark.parametrize(
    "ctx",
    [
        AuthContext(None, "api-key", "superadmin", None, is_superadmin=True),
        AuthContext(None, "api-key", "tenant-key", 4, is_superadmin=False),
        AuthContext(9, "other-user", "tenant-editor", 16, {"geo.content": "edit"}),
        AuthContext(9, "unbound-user", "superadmin", None, {"geo.content": "edit"}),
    ],
)
def test_atomic_foundation_rejects_superadmin_api_key_cross_tenant_and_unbound_user(ctx):
    http, session = _foundation_http(ctx)

    response = http.post(
        "/api/v1/geo/integration/scheduler-safe-foundation",
        json=_runbook_foundation_payload(),
    )

    assert response.status_code == 403
    session.scalar.assert_not_awaited()
    session.get.assert_not_awaited()
    session.commit.assert_not_awaited()


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
