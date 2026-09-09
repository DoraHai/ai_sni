import asyncio
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "test-secret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00+00:00")
os.environ.setdefault(
    "CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app import seo_main
from app.seo_demo_runtime import (
    DEMO_SAFE_POST_PATHS,
    demo_request_is_allowed,
    seo_scheduler_may_start,
    validate_seo_demo_runtime_settings,
)
from app import seo_scheduler


def settings(**overrides):
    values = {
        "app_env": "demo",
        "seo_demo_mode": True,
        "seo_scheduler_enabled": False,
        "seo_external_actions_enabled": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_demo_runtime_requires_all_three_fail_closed_flags():
    policy = validate_seo_demo_runtime_settings(settings())
    assert policy.demo_mode is True
    assert policy.scheduler_enabled is False
    assert policy.external_actions_enabled is False
    unsafe = (
        settings(seo_demo_mode=False),
        settings(seo_scheduler_enabled=True),
        settings(seo_external_actions_enabled=True),
    )
    for candidate in unsafe:
        with pytest.raises(RuntimeError, match="Unsafe SEO demo"):
            validate_seo_demo_runtime_settings(candidate)
    with pytest.raises(RuntimeError, match="APP_ENV=demo"):
        validate_seo_demo_runtime_settings(settings(app_env="prod"))


def test_demo_http_policy_allows_reads_login_and_exact_local_previews():
    demo = settings()
    for method in ("GET", "HEAD", "OPTIONS"):
        assert demo_request_is_allowed(demo, method, "/api/v1/seo/overview")
    for path in DEMO_SAFE_POST_PATHS:
        assert demo_request_is_allowed(demo, "POST", path)
        assert demo_request_is_allowed(demo, "POST", path + "/")
    assert demo_request_is_allowed(demo, "POST", "/api/v1/auth/login")


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/seo/site/crawl-runs",
        "/api/v1/seo/content-ai/assist",
        "/api/v1/seo/traffic/gsc/test",
        "/api/v1/seo/content-distribution/connections/1/test",
        "/api/v1/seo/content-distribution/publish",
        "/api/v1/seo/content-distribution/publications/1/materials",
        "/api/v1/seo/rank-serp/collect",
        "/api/v1/seo/backlinks/discover",
        "/api/v1/seo/competitors/1/collect",
        "/api/v1/seo/qa/questions/import",
        "/api/v1/seo/tasks",
    ],
)
def test_demo_http_policy_rejects_external_and_mutating_actions(path):
    assert not demo_request_is_allowed(settings(), "POST", path)
    assert not demo_request_is_allowed(settings(), "PATCH", path)
    assert demo_request_is_allowed(settings(app_env="dev", seo_demo_mode=False), "POST", path)


def test_demo_scheduler_entry_does_not_lock_register_or_start():
    demo = settings()
    assert not seo_scheduler_may_start(demo)
    with (
        patch.object(seo_scheduler, "get_settings", return_value=demo),
        patch.object(seo_scheduler, "_acquire_scheduler_lock") as acquire,
        patch.object(seo_scheduler.seo_scheduler, "add_job") as add_job,
        patch.object(seo_scheduler.seo_scheduler, "start") as start,
    ):
        seo_scheduler._start_seo_scheduler()
    acquire.assert_not_called()
    add_job.assert_not_called()
    start.assert_not_called()


def test_demo_lifespan_does_not_start_or_stop_scheduler_or_recovery_workers():
    demo = settings()

    async def run():
        with (
            patch.object(seo_main, "settings", demo),
            patch.object(seo_main, "start_seo_scheduler") as start,
            patch.object(seo_main, "shutdown_seo_scheduler") as stop,
        ):
            async with seo_main.lifespan(seo_main.app):
                pass
        start.assert_not_called()
        stop.assert_not_called()

    asyncio.run(run())


def test_demo_middleware_rejects_before_route_and_preserves_read_login_paths():
    demo = settings()
    with patch.object(seo_main, "settings", demo), TestClient(seo_main.app) as client:
        blocked = client.post(
            "/api/v1/seo/site/crawl-runs",
            json={"tenant_id": 1, "site_id": 1},
        )
        assert blocked.status_code == 403
        assert blocked.json()["code"] == "seo_demo_runtime_read_only"

        # These routes are deliberately not mounted on this isolated SEO app;
        # 404 proves the middleware passed them through instead of blocking.
        assert client.get("/not-a-route").status_code == 404
        assert client.post("/api/v1/auth/login", json={}).status_code == 404
