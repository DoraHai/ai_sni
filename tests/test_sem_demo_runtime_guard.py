from types import SimpleNamespace
import asyncio
from unittest.mock import Mock
from unittest.mock import AsyncMock

import pytest

import app.config as config_module
from app.config import (
    SemDemoRuntimeBlockedError,
    enforce_sem_demo_runtime_config,
    reject_sem_demo_async_action,
    sem_demo_http_mutation_blocked,
)


FLAG_NAMES = (
    "sem_scheduler_enabled",
    "sem_baidu_client_enabled",
    "sem_external_actions_enabled",
    "sem_write_endpoints_enabled",
)


def _settings(*, app_env: str = "demo", **overrides):
    values = {name: False for name in FLAG_NAMES}
    values.update(overrides)
    return SimpleNamespace(app_env=app_env, **values)


def test_demo_startup_requires_all_four_flags_explicitly_false():
    enforce_sem_demo_runtime_config(_settings())

    for name in FLAG_NAMES:
        values = {flag: False for flag in FLAG_NAMES if flag != name}
        with pytest.raises(RuntimeError, match=name):
            enforce_sem_demo_runtime_config(SimpleNamespace(app_env="demo", **values))
        with pytest.raises(RuntimeError, match=name):
            enforce_sem_demo_runtime_config(_settings(**{name: True}))


def test_non_demo_defaults_remain_compatible():
    enforce_sem_demo_runtime_config(SimpleNamespace(app_env="prod"))
    enforce_sem_demo_runtime_config(SimpleNamespace(app_env="dev"))


def test_demo_http_gate_allows_login_and_reads_only():
    settings = _settings()
    assert not sem_demo_http_mutation_blocked(
        settings, "POST", "/api/v1/auth/login"
    )
    assert not sem_demo_http_mutation_blocked(
        settings, "GET", "/api/v1/dashboard/cockpit"
    )
    assert sem_demo_http_mutation_blocked(
        settings, "POST", "/api/v1/admin/sync-all"
    )
    assert sem_demo_http_mutation_blocked(
        settings, "PATCH", "/api/v1/keywords/1"
    )
    assert sem_demo_http_mutation_blocked(
        settings, "GET", "/api/oauth/baidu/callback"
    )
    assert not sem_demo_http_mutation_blocked(
        _settings(app_env="prod", sem_write_endpoints_enabled=True),
        "POST",
        "/api/v1/admin/sync-all",
    )
    assert sem_demo_http_mutation_blocked(
        _settings(app_env="prod", sem_write_endpoints_enabled=False),
        "POST",
        "/api/v1/admin/sync-all",
    )


def test_internal_async_guard_rejects_before_function_body(monkeypatch):
    called = False

    @reject_sem_demo_async_action("test action")
    async def action():
        nonlocal called
        called = True

    monkeypatch.setattr(config_module, "get_settings", lambda: _settings())
    async def run():
        with pytest.raises(SemDemoRuntimeBlockedError, match="test action"):
            await action()

    asyncio.run(run())
    assert called is False


def test_explicit_external_action_flag_disables_non_demo_runtime(monkeypatch):
    called = False

    @reject_sem_demo_async_action("test action")
    async def action():
        nonlocal called
        called = True

    settings = _settings(app_env="prod", sem_external_actions_enabled=False)
    monkeypatch.setattr(config_module, "get_settings", lambda: settings)

    async def run():
        with pytest.raises(SemDemoRuntimeBlockedError, match="test action"):
            await action()

    asyncio.run(run())
    assert called is False


def test_baidu_client_is_blocked_before_credentials_or_transport(monkeypatch):
    import app.baidu.client as client_module

    monkeypatch.setattr(client_module, "get_settings", lambda: _settings())
    with pytest.raises(SemDemoRuntimeBlockedError, match="Baidu client access"):
        client_module.BaiduAPIClient(username="", access_token="")

    unsafe_flags = _settings(
        sem_baidu_client_enabled=True,
        sem_external_actions_enabled=True,
        sem_write_endpoints_enabled=True,
    )
    unsafe_flags.baidu_api_base_url = "https://api.baidu.com"
    monkeypatch.setattr(client_module, "get_settings", lambda: unsafe_flags)
    with pytest.raises(SemDemoRuntimeBlockedError, match="Baidu client access"):
        client_module.BaiduAPIClient(username="admin", access_token="token")


def test_demo_lifespan_never_starts_or_stops_scheduler(monkeypatch):
    import app.main as main_module

    settings = _settings()
    settings.app_base_url = "https://demo.example.invalid"
    settings.baidu_default_username = ""
    start = Mock()
    stop = Mock()
    monkeypatch.setattr(main_module, "settings", settings)
    monkeypatch.setattr(main_module, "enforce_production_secrets", Mock())
    monkeypatch.setattr(main_module, "start_scheduler", start)
    monkeypatch.setattr(main_module, "shutdown_scheduler", stop)

    async def run():
        async with main_module.lifespan(None):
            start.assert_not_called()
            stop.assert_not_called()

    asyncio.run(run())
    start.assert_not_called()
    stop.assert_not_called()


def test_demo_http_middleware_blocks_admin_key_before_route_dependencies(monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main_module

    settings = _settings()
    settings.app_base_url = "https://demo.example.invalid"
    settings.baidu_default_username = ""
    monkeypatch.setattr(main_module, "settings", settings)
    monkeypatch.setattr(main_module, "enforce_production_secrets", Mock())
    monkeypatch.setattr(main_module, "start_scheduler", Mock())
    monkeypatch.setattr(main_module, "shutdown_scheduler", Mock())

    with TestClient(main_module.app) as client:
        response = client.post(
            "/api/v1/admin/init-self-auth-account",
            params={"tenant_name": "must-not-run"},
            headers={"X-API-Key": "cannot-bypass-demo"},
        )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "SEM demo runtime is read-only",
        "code": "sem_demo_read_only",
    }


@pytest.mark.parametrize(
    ("module_name", "function_name"),
    [
        ("app.baidu.sync", "sync_keyword_report_for_all_active_accounts"),
        ("app.baidu.oauth", "create_authorization_url"),
        ("app.baidu.oauth", "refresh_expiring_oauth_grants"),
        ("app.baidu.writeback", "apply_account_budget_writeback"),
        ("app.baidu.writeback", "apply_keyword_writeback"),
    ],
)
def test_internal_entry_points_cannot_bypass_demo_gate(
    monkeypatch, module_name, function_name
):
    module = __import__(module_name, fromlist=[function_name])
    monkeypatch.setattr(config_module, "get_settings", lambda: _settings())
    function = getattr(module, function_name)
    async def run():
        with pytest.raises(SemDemoRuntimeBlockedError):
            await function()

    asyncio.run(run())


def test_all_baidu_sync_oauth_and_writeback_entry_points_are_guarded():
    import app.baidu.oauth as oauth_module
    import app.baidu.sync as sync_module
    import app.baidu.writeback as writeback_module

    names = [
        name for name in dir(sync_module)
        if name.startswith("sync_") and callable(getattr(sync_module, name))
    ]
    names += [
        "create_authorization_url",
        "consume_oauth_state",
        "_post_oauth",
        "exchange_auth_code",
        "fetch_authorized_accounts",
        "persist_authorization",
        "refresh_grant",
        "refresh_expiring_oauth_grants",
    ]
    names += [
        name for name in dir(writeback_module)
        if name.startswith("apply_") and callable(getattr(writeback_module, name))
    ]
    for name in names:
        module = (
            sync_module if hasattr(sync_module, name)
            else writeback_module if hasattr(writeback_module, name)
            else oauth_module
        )
        assert hasattr(getattr(module, name), "__wrapped__"), name

    from app.scheduler import refresh_keyword_workbench_snapshot

    assert hasattr(refresh_keyword_workbench_snapshot, "__wrapped__")


def test_demo_disables_external_model_calls_even_when_key_exists(monkeypatch):
    import app.ai.deepseek as deepseek_module

    settings = _settings()
    settings.dashscope_api_key = "must-not-be-used"
    settings.deepseek_api_key = "must-not-be-used"
    monkeypatch.setattr(deepseek_module, "get_settings", lambda: settings)
    monkeypatch.setattr(config_module, "get_settings", lambda: settings)

    assert deepseek_module.is_enabled() is False

    async def run():
        with pytest.raises(SemDemoRuntimeBlockedError, match="external model access"):
            await deepseek_module.chat_json("system", "user")

    asyncio.run(run())


def test_demo_profile_returns_existing_summary_even_when_force_requested(monkeypatch):
    import app.ai.customer_profile as profile_module

    monkeypatch.setattr(profile_module, "get_settings", lambda: _settings())
    tenant = SimpleNamespace(profile_summary="stored demo summary")

    result = asyncio.run(
        profile_module.generate_summary(
            SimpleNamespace(), tenant, {}, force=True
        )
    )
    assert result == "stored demo summary"


def test_demo_insight_reads_existing_row_without_generation(monkeypatch):
    from datetime import date
    import app.ai.insight as insight_module

    stored = object()
    session = SimpleNamespace(scalar=AsyncMock(return_value=stored))
    tenant = SimpleNamespace(id=990000001)
    monkeypatch.setattr(insight_module, "get_settings", lambda: _settings())

    result = asyncio.run(
        insight_module.generate_insight(
            session, tenant, target_date=date(2026, 9, 8), force=True
        )
    )
    assert result is stored
    session.scalar.assert_awaited_once()
