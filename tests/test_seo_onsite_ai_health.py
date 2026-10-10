"""Protocol and process-local health evidence, without supplier calls."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app import seo_onsite_ai_health as health, seo_onsite_ai_jobs as jobs
from app.api import seo_onsite_ai as api
from app.security.auth import AuthContext

ADMIN = AuthContext(91, "health-admin", "global", None,
                    {"settings.accounts": "edit", "settings.customers": "edit"})


@pytest.fixture(autouse=True)
def clean_health(monkeypatch):
    monkeypatch.setattr(health, "_owner", False)
    monkeypatch.setattr(health, "_stopped", False)
    monkeypatch.setattr(health, "_tick_monotonic", None)
    monkeypatch.setattr(health, "_tick", {
        "last_tick_at": None, "last_attempted": 0, "last_completed": 0, "last_error_code": None})
    monkeypatch.setattr(health, "get_settings", lambda: SimpleNamespace(
        seo_scheduler_enabled=True, seo_external_actions_enabled=True, seo_demo_mode=False, app_env="test"))


@pytest.mark.parametrize("headers", [[], [("X-Snipers-Onsite-Protocol", "")],
    [("X-Snipers-Onsite-Protocol", "sync-v0")], [("X-Snipers-Onsite-Protocol", "DURABLE-V1")],
    [("X-Snipers-Onsite-Protocol", " durable-v1")],
    [("X-Snipers-Onsite-Protocol", "durable-v1")] * 2])
def test_bad_protocol_stops_before_any_business_session_use(headers):
    async def run():
        app = FastAPI()
        app.include_router(api.router, prefix="/api/v1/seo")
        app.dependency_overrides[api.require_seo_scoped_auth] = lambda: ADMIN
        # Any attempted SQL/lock/admission path on this sentinel would fail.
        app.dependency_overrides[api.get_seo_session] = lambda: object()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/seo/workbench/onsite-tasks/1/ai-proposal", headers=headers,
                json={"tenant_id": 4, "site_id": 2, "expected_revision": 1,
                      "request_id": str(uuid4()), "mode": "initial"})
        assert response.status_code == 409
        assert response.json() == {"detail": "工作台版本过旧，请刷新页面后重试", "code": "onsite_client_upgrade_required"}
        assert response.headers["cache-control"] == "no-store"
    asyncio.run(run())


@pytest.mark.parametrize("ctx", [
    AuthContext(None, "api-key", "超级管理员", None, {}, is_superadmin=True),
    AuthContext(7, "bound", "超级管理员", 4, ADMIN.permissions, is_superadmin=True),
    AuthContext(7, "viewer", "超级管理员", None, {"settings.accounts": "view", "settings.customers": "edit"}),
    AuthContext(7, "partial", "global", None, {"settings.accounts": "edit"}),
    AuthContext(7, "advisor", "advisor", None, {"seo.site": "edit", "seo.content": "edit"}),
    None,
])
def test_health_rejects_non_global_admin_before_queue_query(ctx):
    async def run():
        app = FastAPI()
        app.include_router(api.router, prefix="/api/v1/seo")
        async def auth():
            if ctx is None:
                raise HTTPException(401, "未登录")
            return ctx
        def never_session():
            pytest.fail("unauthorized health query opened business session")
        app.dependency_overrides[api.require_auth] = auth
        app.dependency_overrides[api.get_primary_session] = never_session
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/seo/workbench/onsite-ai/health")
        assert response.status_code == (401 if ctx is None else 403)
    asyncio.run(run())


def test_worker_start_stop_errors_and_stale_evidence_are_honest(monkeypatch):
    time = [100.0]
    monkeypatch.setattr(health, "monotonic", lambda: time[0])
    initial = health.worker_status()
    assert initial["state"] == "unverified" and initial["evidence"] is None
    assert initial["last_tick_at"] is None and not initial["verified"]
    health.record_tick(2, 2)
    assert health.worker_status() == initial  # unrelated direct calls cannot prove ownership
    health.worker_started()
    assert health.worker_status()["state"] == "unverified"
    health.record_tick(2, 2)
    active = health.worker_status()
    assert active["state"] == "active" and active["verified"] and active["scope"] == "this_process"
    assert datetime.fromisoformat(active["last_tick_at"]).utcoffset().total_seconds() == 0
    assert health.worker_status() == active  # reads cannot manufacture a heartbeat
    time[0] += health.STALE_SECONDS + 1
    stale = health.worker_status()
    assert stale["state"] == "unverified" and not stale["verified"]
    assert stale["last_tick_at"] == active["last_tick_at"] and stale["evidence"] == {"kind": "local_tick", "scope": "this_process"}
    health.record_tick(2, 1, failed=True)
    assert health.worker_status()["state"] == "degraded" and health.worker_status()["verified"]
    health.worker_stopped()
    assert health.worker_status()["state"] == "stopped"
    health.worker_started()
    assert health.worker_status()["last_tick_at"] is None
    monkeypatch.setattr(health, "get_settings", lambda: SimpleNamespace(seo_scheduler_enabled=False))
    assert health.worker_status()["state"] == "stopped"


@pytest.mark.parametrize("failed", [False, True])
def test_real_worker_round_records_idle_tick_or_safe_failure(monkeypatch, failed):
    health.worker_started()
    session = SimpleNamespace(execute=AsyncMock())
    if failed:
        session.execute.side_effect = SQLAlchemyError("secret DSN and customer prompt")
    else:
        session.execute.return_value = SimpleNamespace(all=lambda: [])
    @asynccontextmanager
    async def sessions():
        yield session
    async def run():
        if failed:
            with pytest.raises(SQLAlchemyError):
                await jobs.run_onsite_ai_jobs(sessions=sessions)
        else:
            await jobs.run_onsite_ai_jobs(sessions=sessions)
        value = health.worker_status()
        assert value["state"] == ("degraded" if failed else "active")
        assert value["last_tick_at"] is not None
        assert value["last_attempted"] == value["last_completed"] == 0
        assert "secret" not in str(value)
    asyncio.run(run())


def test_health_database_failure_is_503_not_empty_queue(monkeypatch):
    monkeypatch.setattr(health, "queue_status", AsyncMock(side_effect=SQLAlchemyError("secret database URL")))
    response = asyncio.run(api.onsite_ai_health(ADMIN, object()))
    assert response.status_code == 503 and response.headers["cache-control"] == "no-store"
    assert b'onsite_ai_health_unavailable' in response.body
    assert b'secret' not in response.body and b'queued' not in response.body


def test_scheduler_shutdown_clears_ownership_even_when_shutdown_fails(monkeypatch):
    from app import seo_scheduler as scheduler
    def fail(**kwargs):
        raise RuntimeError("failure")
    health.worker_started()
    health.record_tick(0, 0)
    monkeypatch.setattr(scheduler, "seo_scheduler", SimpleNamespace(running=True, shutdown=fail))
    monkeypatch.setattr(scheduler, "release_file_lock", lambda handle: None)
    monkeypatch.setattr(scheduler, "_lock_fh", None)
    with pytest.raises(RuntimeError):
        scheduler.shutdown_seo_scheduler()
    assert health.worker_status()["state"] == "stopped"


def test_one_candidate_failure_preserves_next_candidate_and_degrades_evidence(monkeypatch):
    health.worker_started()
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [
        (1, 4, 2, "first"), (2, 5, 3, "second")])))
    @asynccontextmanager
    async def sessions():
        yield session
    async def execute(task_id, *args, **kwargs):
        if task_id == 1:
            raise RuntimeError("PRIVATE-CUSTOMER-ERROR")
        return "ready"
    monkeypatch.setattr(jobs, "execute_request", execute)
    asyncio.run(jobs.run_onsite_ai_jobs(sessions=sessions))
    status = health.worker_status()
    assert status["state"] == "degraded" and status["verified"]
    assert status["last_attempted"] == 2 and status["last_completed"] == 1
    assert status["last_error_code"] == "worker_batch_failed"
    assert "PRIVATE" not in str(status)
