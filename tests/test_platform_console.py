"""Authorization, safe projections and native read-only inventory checks."""
import asyncio
import json
import os
import uuid

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import platform_console as console
from app.security.auth import AuthContext, require_auth


def context(*, tenant=None, permissions=None, user_id=7):
    return AuthContext(user_id, "test-admin", "管理员", tenant,
                       permissions if permissions is not None else
                       {"settings.accounts": "edit", "settings.customers": "edit"})


@pytest.mark.parametrize("ctx", [
    context(tenant=1), context(permissions={}),
    context(permissions={"settings.accounts": "edit"}),
    context(permissions={"settings.accounts": "view", "settings.customers": "edit"}),
    AuthContext(None, "api-key", "超级管理员", None, is_superadmin=True),
])
def test_non_global_or_partial_roles_cannot_read_console(ctx):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(console.require_console_admin(ctx))
    assert exc.value.status_code == 403


def test_global_named_admin_can_read_and_endpoint_is_guarded(monkeypatch):
    assert asyncio.run(console.require_console_admin(context())).user_id == 7
    app = FastAPI()
    app.include_router(console.router)
    with TestClient(app) as client:
        assert client.get("/api/v1/admin/console/snapshot").status_code == 401
    app.dependency_overrides[require_auth] = lambda: context(tenant=1)
    with TestClient(app) as client:
        assert client.get("/api/v1/admin/console/snapshot").status_code == 403
    # This requires no database access: rejection happens before the reader.


@pytest.mark.parametrize(("raw", "expected"), [
    ("https://user:PRIVATE@example.com/api/search?api_key=PRIVATE#PRIVATE", "example.com/api/search"),
    ("/api/v1/search?token=PRIVATE", "/api/v1/search"),
    (None, None),
])
def test_endpoint_addresses_cannot_expose_query_or_url_credentials(raw, expected):
    assert console.safe_endpoint(raw) == expected


def test_projection_excludes_credentials_and_business_payloads():
    serialized = str(console.PROJECTIONS)
    for name in ["password_hash", "token_encrypted", "api_key_encrypted", "module_settings",
                 "request_meta", "result_meta", "params", "error"]:
        assert f"'{name}'" not in serialized
    assert console.machine_code("key=PRIVATE") is None
    assert console.machine_code("provider_timeout") == "provider_timeout"


def test_control_writes_use_same_admin_boundary_and_never_echo_secrets(monkeypatch):
    monkeypatch.setenv('API_CONTROLS_ENABLED','true')
    app = FastAPI()
    app.include_router(console.router)
    payload = {'key':'PRIVATE-SECRET','value':{'key':'PRIVATE-SECRET'}}
    with TestClient(app) as client:
        assert client.post('/api/v1/admin/console/controls',json=payload).status_code==401
        app.dependency_overrides[require_auth]=lambda:context(tenant=1)
        assert client.post('/api/v1/admin/console/controls',json=payload).status_code==403
        app.dependency_overrides[require_auth]=lambda:context()
        response=client.post('/api/v1/admin/console/controls',json=payload)
        assert response.status_code==422 and 'PRIVATE-SECRET' not in response.text
        response=client.post('/api/v1/admin/console/controls',content='PRIVATE-SECRET'*1000)
        assert response.status_code==422 and 'PRIVATE-SECRET' not in response.text


def test_missing_optional_tables_are_unknown_not_zero():
    result = asyncio.run(console.read_table(None, {}, "seo_ai_operations"))
    assert result == {"state": "unavailable", "total": None, "rows": [], "truncated": False}


def test_native_inventory_is_read_only_and_scoped_to_owned_schema(monkeypatch):
    raw = os.getenv("PLATFORM_CONSOLE_TEST_DATABASE_URL") or os.getenv("SEO_WORKFLOW_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("Set an explicit local test PostgreSQL URL to run native inventory verification")
    url = make_url(raw)
    assert url.host in {"127.0.0.1", "localhost"} and "test" in url.database.lower()
    schema = "platform_console_" + uuid.uuid4().hex

    async def run():
        setup = create_async_engine(raw)
        scoped = create_async_engine(raw, connect_args={"server_settings": {"search_path": schema}})
        try:
            async with setup.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with scoped.begin() as c:
                await c.execute(text("CREATE TABLE tenants(id int, name text, industry text, created_at timestamp)"))
                await c.execute(text("INSERT INTO tenants VALUES(1, 'Test customer', 'Test', CURRENT_TIMESTAMP)"))
                await c.execute(text("CREATE TABLE tenant_modules(id int, tenant_id int, module_code text, status text, expires_at date, module_settings jsonb)"))
                today = console.datetime.now(console.ZoneInfo("Asia/Shanghai")).date().isoformat()
                settings = {"private_key": "DO_NOT_RETURN", "seo_daily_usage": {"date": today, "ai_requests": 4, "crawl_urls": 8, "workbench_chat_requests": 2}}
                await c.execute(text("INSERT INTO tenant_modules VALUES(1,1,'seo','active',NULL,CAST(:settings AS jsonb))"), {"settings": json.dumps(settings)})
                await c.execute(text("CREATE TABLE api_audit_logs(id int, tenant_id int, endpoint text, request_id text, status_code int, error_code text, latency_ms int, created_at timestamp)"))
                await c.execute(text("INSERT INTO api_audit_logs VALUES(1,1,'https://user:DO_NOT_RETURN@provider.test/v1?key=DO_NOT_RETURN','req-1',500,'timeout',12,CURRENT_TIMESTAMP)"))
                await c.execute(text("CREATE TABLE geo_async_jobs(id int, tenant_id int, kind text, status text, created_at timestamp, request_meta jsonb)"))
                await c.execute(text("INSERT INTO geo_async_jobs VALUES(1,1,'generate_article','failed',CURRENT_TIMESTAMP,'{\"private\": \"DO_NOT_RETURN\"}')"))
            factory = async_sessionmaker(scoped, expire_on_commit=False)
            monkeypatch.setattr(console, "async_session_factory", factory)
            from starlette.responses import Response
            response = Response()
            result = await console.console_snapshot(response)
            assert response.headers["cache-control"] == "no-store, private"
            assert result["sources"]["tenants"]["total"] == 1
            assert result["sources"]["users"]["total"] is None
            assert result["sources"]["users"]["state"] == "unavailable"
            assert result["calls"]["total"] == result["calls"]["failed"] == 1
            assert result["costs"]["actual_amount"] is None
            assert result["costs"]["usage"][0]["ai_requests"] == 4
            assert result["sources"]["api_audit_logs"]["rows"][0]["endpoint"] == "provider.test/v1"
            assert "DO_NOT_RETURN" not in str(result)
            assert any(a["kind"] == "task_failed" for a in result["alerts"])
            assert any(a["kind"] == "api_errors" for a in result["alerts"])
            # Assert the actual transaction mode used by the endpoint, rather
            # than merely finding a READ ONLY string in its implementation.
            original = console.build_snapshot
            async def check_read_only(session):
                assert await session.scalar(text("SHOW transaction_read_only")) == "on"
                return await original(session)
            monkeypatch.setattr(console, "build_snapshot", check_read_only)
            assert (await console.console_snapshot(Response()))["sources"]["tenants"]["total"] == 1
        finally:
            await scoped.dispose()
            async with setup.begin() as c:
                await c.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await setup.dispose()
    asyncio.run(run())
