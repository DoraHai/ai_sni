import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.geo.demo_runtime import (
    DEMO_DISABLE_FLAGS,
    GeoDemoRuntimeConfigurationError,
    demo_request_is_read_only,
    require_geo_demo_safe_request,
    validate_geo_demo_runtime,
)

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test")
os.environ.setdefault("BAIDU_SECRET_KEY", "test")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00Z")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test")


def demo_env():
    return {
        "GEO_DEMO_RUNTIME": "true",
        **{key: "false" for key in DEMO_DISABLE_FLAGS},
        "BAIDU_WRITE_DRY_RUN": "true",
        "CHINAZ_API_ENABLED": "false",
        "SEO_RANK_SCHEDULER_ENABLED": "false",
    }


def demo_settings():
    values = {
        "app_env": "demo",
        "geo_demo_runtime": True,
        "baidu_write_dry_run": True,
        "chinaz_api_enabled": False,
        "seo_rank_scheduler_enabled": False,
    }
    values.update({field: False for field in DEMO_DISABLE_FLAGS.values()})
    return SimpleNamespace(**values)


def request(method, path):
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "scheme": "https",
            "server": ("demo.invalid", 443),
        }
    )


def test_demo_runtime_requires_every_explicit_disable_switch():
    settings = demo_settings()
    assert validate_geo_demo_runtime(settings, demo_env()) is True
    for env_key in DEMO_DISABLE_FLAGS:
        env = demo_env()
        del env[env_key]
        with pytest.raises(GeoDemoRuntimeConfigurationError, match=env_key):
            validate_geo_demo_runtime(settings, env)


def test_demo_runtime_rejects_true_switch_and_nonempty_model_key():
    settings = demo_settings()
    env = demo_env()
    env["GEO_PUBLISHING_ENABLED"] = "true"
    with pytest.raises(GeoDemoRuntimeConfigurationError, match="GEO_PUBLISHING_ENABLED"):
        validate_geo_demo_runtime(settings, env)
    settings.geo_publishing_enabled = False
    settings.geo_openai_api_key = "live-key"
    with pytest.raises(GeoDemoRuntimeConfigurationError, match="external credentials"):
        validate_geo_demo_runtime(settings, demo_env())


def test_non_demo_keeps_existing_runtime_behavior():
    assert validate_geo_demo_runtime(SimpleNamespace(app_env="production"), {}) is False


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/geo/tenants",
        "/api/v1/geo/integration/read/answers",
        "/api/v1/geo/integration/read/content-tasks/14",
        "/api/v1/geo/integration/metrics/snapshot",
        "/api/v1/geo/integration/tasks",
    ],
)
def test_demo_allows_only_declared_read_routes(path):
    assert demo_request_is_read_only(request("GET", path))


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/geo/integration/tasks"),
        ("POST", "/api/v1/geo/content-tasks/14/generate"),
        ("POST", "/api/v1/geo/visibility-patrol-runs"),
        ("POST", "/api/v1/geo/content-tasks/14/variants"),
        ("POST", "/api/v1/geo/content-tasks/14/push"),
        ("PATCH", "/api/v1/geo/publishing-channels/1"),
        ("GET", "/api/v1/geo/oauth/social/callback"),
        ("GET", "/api/v1/geo/content-tasks/14"),
        ("GET", "/api/v1/geo/deliverables/share/token"),
        ("GET", "/api/v1/geo/integration-unsafe"),
    ],
)
def test_demo_rejects_execution_config_oauth_and_legacy_reads(method, path):
    assert not demo_request_is_read_only(request(method, path))


def test_request_dependency_rejects_admin_write_in_demo():
    with patch("app.geo.demo_runtime.get_settings", return_value=demo_settings()), patch(
        "app.geo.demo_runtime.validate_geo_demo_runtime", return_value=True
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                require_geo_demo_safe_request(
                    request("POST", "/api/v1/geo/content-tasks/14/generate")
                )
            )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "geo_demo_runtime_read_only"


def test_request_dependency_allows_integration_read_in_demo():
    with patch("app.geo.demo_runtime.get_settings", return_value=demo_settings()), patch(
        "app.geo.demo_runtime.validate_geo_demo_runtime", return_value=True
    ):
        asyncio.run(
            require_geo_demo_safe_request(
                request("GET", "/api/v1/geo/integration/read/answers")
            )
        )


def test_all_mounted_geo_routes_have_demo_request_guard():
    from app.geo.content.oauth_public import router as public_router
    from app.geo.routes import router as geo_router

    for mounted_router in (geo_router, public_router):
        assert mounted_router.routes
        for route in mounted_router.routes:
            dependency_calls = {
                dependency.call for dependency in route.dependant.dependencies
            }
            assert require_geo_demo_safe_request in dependency_calls, route.path


def test_demo_lifespan_starts_no_recovery_scheduler_or_supervisor():
    from app import geo_main

    with patch.object(geo_main, "validate_geo_demo_runtime", return_value=True), patch.object(
        geo_main, "enforce_production_secrets"
    ) as prod_guard, patch.object(geo_main, "start_geo_scheduler") as start_scheduler, patch.object(
        geo_main, "supervise_geo_followups", new=AsyncMock()
    ) as followups, patch("app.geo.content.async_jobs.recover_jobs_on_startup", new=AsyncMock()) as recover_jobs, patch(
        "app.geo.content.patrol.recover_patrol_runs_on_startup", new=AsyncMock()
    ) as recover_patrols:

        async def enter():
            async with geo_main._lifespan(Mock()):
                return None

        asyncio.run(enter())

    prod_guard.assert_called_once()
    start_scheduler.assert_not_called()
    followups.assert_not_awaited()
    recover_jobs.assert_not_awaited()
    recover_patrols.assert_not_awaited()
