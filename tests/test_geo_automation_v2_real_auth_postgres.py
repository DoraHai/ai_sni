"""Real login/JWT/RBAC/entitlement acceptance for the GEO v2 HTTP adapter."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app import automation_projects as core
from app.database import get_session
from app.geo import automation_routes
from app.geo.automation_v2_adapter import live_basis
from app.models import GeoAnswerSnapshot, TenantModule
from app.models.role import Role
from app.models.user import User
from app.security import auth as security_auth
from app.security.auth import hash_password
from test_geo_automation_v2_postgres import foundation
from test_geo_project_scope_postgres import database

_AUTH_SPEC = importlib.util.spec_from_file_location(
    "geo_real_auth_api", Path(__file__).parents[1] / "app" / "api" / "auth.py")
assert _AUTH_SPEC and _AUTH_SPEC.loader
auth_api = importlib.util.module_from_spec(_AUTH_SPEC)
_AUTH_SPEC.loader.exec_module(auth_api)

pytestmark = pytest.mark.skipif(
    not os.getenv("GEO_TEST_POSTGRES_URL"), reason="requires dedicated PostgreSQL"
)

PASSWORD = "Geo-real-auth-test-2026"
PERMISSIONS = {
    "geo.assets": "edit",
    "geo.content": "edit",
    "settings.accounts": "edit",
    "settings.customers": "edit",
}


async def prepare_identities(sessions):
    async with sessions() as db:
        role = await db.get(Role, 5)
        role.permissions = dict(PERMISSIONS)
        advisor = await db.get(User, 7)
        advisor.password_hash = hash_password(PASSWORD)
        advisor.tenant_id = None
        db.add(Role(id=6, name="tenant fixture advisor", permissions={
            "geo.assets": "edit", "geo.content": "edit"}))
        db.add(User(id=8, username="tenant fixture advisor", display_name="tenant advisor",
                    password_hash=hash_password(PASSWORD), role_id=6, tenant_id=1,
                    is_active=True))
        await db.commit()


def application(sessions):
    app = FastAPI()
    app.include_router(auth_api.router)
    app.include_router(automation_routes.router, prefix="/api/v1/geo")
    app.include_router(automation_routes.health_router, prefix="/api/v1/geo")

    async def session_override():
        async with sessions() as db:
            yield db

    # The database is isolated, but authentication itself is never overridden.
    app.dependency_overrides[get_session] = session_override
    return app


async def login(client, username="scope fixture advisor"):
    response = await client.post("/api/v1/auth/login", json={
        "username": username, "password": PASSWORD,
    })
    assert response.status_code == 200, response.text
    token = response.json()["token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["user"]["username"] == username
    return token


def headers(token):
    return {"Authorization": f"Bearer {token}"}


def configuration(basis):
    return {
        "contract_version": 2,
        "operations": ["visibility_patrol"],
        "targets": basis["targets"],
        "service_plan": basis["service_plan"],
        "source_bindings": basis["source_bindings"],
        "cycle": {"mode": "daily", "enabled": True},
        "limits": {"max_dispatches_per_run": 20, "max_external_calls_per_run": 20},
        "stop_condition": "drafts_ready_or_blocked",
        "owner_user_id": 7,
    }


async def configure_start(client, token, captured):
    basis_response = await client.get(
        "/api/v1/geo/workbench/automation-projects/10/configuration-basis",
        params={"tenant_id": 1, "operation": "visibility_patrol"}, headers=headers(token),
    )
    assert basis_response.status_code == 200, basis_response.text
    basis = basis_response.json()
    chosen = next(row for row in basis["targets"] if row["variant"] == "deepseek")
    basis["targets"] = [{key: chosen[key] for key in (
        "operation", "object_type", "object_id", "source_revision", "source_hash", "variant"
    )}]
    configured = await client.put(
        "/api/v1/geo/workbench/automation-projects/10/control",
        json={"tenant_id": 1, "request_id": str(uuid4()), "expected_version": 0,
              "configuration": configuration(basis)}, headers=headers(token),
    )
    assert configured.status_code == 200, configured.text
    started = await client.post(
        "/api/v1/geo/workbench/automation-projects/10/control",
        json={"tenant_id": 1, "request_id": str(uuid4()),
              "expected_version": configured.json()["version"], "action": "start"},
        headers=headers(token),
    )
    assert started.status_code == 200, started.text
    assert captured and captured[-1][1] == started.json()["current_run_id"]
    return started.json()


def test_real_login_jwt_database_identity_and_complete_read_chain(monkeypatch):
    async def scenario():
        async with database() as sessions:
            await foundation(sessions)
            await prepare_identities(sessions)
            captured = []

            async def capture_run(key, run_id):
                captured.append((key, run_id))

            monkeypatch.setattr(automation_routes, "run_automation", capture_run)
            app = application(sessions)
            async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                token = await login(client)
                started = await configure_start(client, token, captured)
                run_id = started["current_run_id"]
                for path in (
                    f"/api/v1/geo/workbench/automation-projects/10/control?tenant_id=1",
                    f"/api/v1/geo/workbench/automation-projects/10/runs/{run_id}?tenant_id=1",
                    f"/api/v1/geo/workbench/automation-projects/10/runs/{run_id}/events?tenant_id=1",
                    f"/api/v1/geo/workbench/automation-projects/10/events/export?tenant_id=1&format=json",
                    "/api/v1/geo/workbench/automation-health",
                ):
                    response = await client.get(path, headers=headers(token))
                    assert response.status_code == 200, (path, response.text)

                assert (await client.get(
                    "/api/v1/geo/workbench/automation-projects/10/control?tenant_id=1"
                )).status_code == 401
                assert (await client.get(
                    "/api/v1/geo/workbench/automation-projects/10/control?tenant_id=1",
                    headers={"X-API-Key": security_auth.get_settings().admin_api_key},
                )).status_code == 403

                tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
                assert (await client.get(
                    "/api/v1/geo/workbench/automation-projects/10/control?tenant_id=1",
                    headers=headers(tampered))).status_code == 401
                expired = jwt.encode({"sub": "7", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
                                     security_auth._jwt_secret(), algorithm=security_auth.JWT_ALG)
                assert (await client.get(
                    "/api/v1/geo/workbench/automation-projects/10/control?tenant_id=1",
                    headers=headers(expired))).status_code == 401

                tenant_token = await login(client, "tenant fixture advisor")
                cross = await client.get(
                    "/api/v1/geo/workbench/automation-projects/12/control?tenant_id=2",
                    headers=headers(tenant_token),
                )
                assert cross.status_code == 403

                async with sessions() as db:
                    (await db.get(Role, 5)).permissions = {"geo.assets": "view"}
                    await db.commit()
                revoked_role = await client.get(
                    "/api/v1/geo/workbench/automation-projects/10/control?tenant_id=1",
                    headers=headers(token),
                )
                assert revoked_role.status_code == 403
                async with sessions() as db:
                    (await db.get(Role, 5)).permissions = dict(PERMISSIONS)
                    (await db.get(User, 7)).is_active = False
                    await db.commit()
                revoked_user = await client.get("/api/v1/auth/me", headers=headers(token))
                assert revoked_user.status_code == 401
    asyncio.run(scenario())


def test_entitlement_revoked_after_authenticated_start_blocks_external_call(monkeypatch):
    provider_calls = 0
    real_run = automation_routes.run_automation

    async def scenario():
        nonlocal provider_calls
        async with database() as sessions:
            await foundation(sessions)
            await prepare_identities(sessions)
            captured = []

            async def capture_run(key, run_id):
                captured.append((key, run_id))

            monkeypatch.setattr(automation_routes, "run_automation", capture_run)
            app = application(sessions)
            async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                token = await login(client)
                started = await configure_start(client, token, captured)

            async with sessions() as db:
                module = await db.scalar(select(TenantModule).where(
                    TenantModule.tenant_id == 1, TenantModule.module_code == "geo"))
                module.status = "disabled"
                await db.commit()

            @asynccontextmanager
            async def factory(*_args, **_kwargs):
                async with sessions() as db:
                    yield db

            class NoNetwork:
                async def __aenter__(self):
                    nonlocal provider_calls
                    provider_calls += 1
                    raise AssertionError("external provider must not be entered after revocation")
                async def __aexit__(self, *_args):
                    return False

            monkeypatch.setattr(automation_routes, "async_session_factory", factory)
            monkeypatch.setattr("app.ai.deepseek.httpx.AsyncClient", lambda *_a, **_k: NoNetwork())
            await real_run(captured[0][0], str(started["current_run_id"]))
            async with sessions() as db:
                run = await core.read_run(db, captured[0][0], started["current_run_id"])
                assert run["steps"][0]["status"] == "blocked"
                assert run["steps"][0]["calls"] == []
    asyncio.run(scenario())
    assert provider_calls == 0


def test_authenticated_pause_during_provider_response_prevents_late_persistence(monkeypatch):
    provider_calls = 0
    real_run = automation_routes.run_automation

    async def scenario():
        nonlocal provider_calls
        async with database() as sessions:
            await foundation(sessions)
            await prepare_identities(sessions)
            captured = []

            async def capture_run(key, run_id):
                captured.append((key, run_id))

            monkeypatch.setattr(automation_routes, "run_automation", capture_run)
            app = application(sessions)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                token = await login(client)
                started = await configure_start(client, token, captured)

                async def provider(_request):
                    nonlocal provider_calls
                    provider_calls += 1
                    current = await client.get(
                        "/api/v1/geo/workbench/automation-projects/10/control?tenant_id=1",
                        headers=headers(token))
                    assert current.status_code == 200
                    paused = await client.post(
                        "/api/v1/geo/workbench/automation-projects/10/control",
                        json={"tenant_id": 1, "request_id": str(uuid4()),
                              "expected_version": current.json()["version"], "action": "pause"},
                        headers=headers(token))
                    assert paused.status_code == 200, paused.text
                    body = {"raw_text": "迟到响应不得写入正式样本。"}
                    return httpx.Response(200, json={
                        "choices": [{"message": {"content": json.dumps(body, ensure_ascii=False)}}]})

                original_client = httpx.AsyncClient

                def provider_client(*_args, **kwargs):
                    return original_client(timeout=kwargs.get("timeout"),
                                           transport=httpx.MockTransport(provider))

                async def credentials(_session, _tenant_id):
                    return {"api_key": "fixture", "base_url": "https://provider.invalid/v1",
                            "model": "fixture-model", "provider": "fixture", "source": "fixture"}

                @asynccontextmanager
                async def factory(*_args, **_kwargs):
                    async with sessions() as db:
                        yield db

                @asynccontextmanager
                async def execution_lock(_run_id):
                    yield True

                async def ai_setting(_session, _tenant_id):
                    return SimpleNamespace(monitoring_stance="hybrid")

                monkeypatch.setattr(automation_routes, "async_session_factory", factory)
                monkeypatch.setattr("app.geo.content.patrol.patrol_execution_lock", execution_lock)
                monkeypatch.setattr("app.geo.content.ai_settings.resolve_llm_credentials", credentials)
                monkeypatch.setattr("app.geo.content.ai_settings.ensure_ai_setting", ai_setting)
                monkeypatch.setattr("app.ai.deepseek.httpx.AsyncClient", provider_client)
                await real_run(captured[0][0], str(started["current_run_id"]))

            async with sessions() as db:
                run = await core.read_run(db, captured[0][0], started["current_run_id"])
                assert run["steps"][0]["status"] == "blocked"
                assert run["steps"][0]["calls"][0]["state"] == "succeeded"
                assert (await core.read_project(db, captured[0][0]))["state"] == "paused"
                persisted = await db.scalar(select(GeoAnswerSnapshot).where(
                    GeoAnswerSnapshot.tenant_id == 1,
                    GeoAnswerSnapshot.prompt_id == 40,
                    GeoAnswerSnapshot.engine == "deepseek",
                    GeoAnswerSnapshot.patrol_run_id.is_not(None)))
                assert persisted is None
    asyncio.run(scenario())
    assert provider_calls == 1
