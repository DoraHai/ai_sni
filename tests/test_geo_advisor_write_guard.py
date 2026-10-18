"""A's policy/transaction tests. Object/assignment contracts are B's boundary.

No supplier calls or production DB: real HTTP/auth/commits on isolated SQLite.
The object-policy doubles here do not replace C's full route/IDOR matrix.
"""
import asyncio
import os
import sys
from uuid import uuid4
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace

import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings, get_settings
from app.database import Base, get_session
from app.models import (GeoOptimizationBusiness, GeoOptimizationPeriod, GeoProject, GeoVisibilityPatrolSettings,
                        Role, Tenant, TenantModule, User)
from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
from app.security.advisor_scope import AdvisorScope, deny
from app.security.advisor_write_handlers import lock_manual_task
from app.security.advisor_write_commit import AdvisorWriteSession
from app.security.advisor_write_routes import WRITE_ROUTES, check_write_fields, match_write_rule
from app.security.auth import require_auth
from test_geo_advisor import legacy, token  # also installs SQLite JSONB compilation


@asynccontextmanager
async def sandbox(tmp_path, monkeypatch, *, enabled=True):
    monkeypatch.setattr(get_settings(), "advisor_scoped_content_writes_enabled", enabled)
    schema = None
    if os.environ.get("GEO_ADVISOR_WRITE_LOCAL_POSTGRES") == "yes":
        from ops.run_geo_checks import validate_ci_database
        url = os.environ["GEO_TEST_POSTGRES_URL"]
        validate_ci_database(url)
        root_engine = create_async_engine(url)
        schema = "geo_a_write_" + uuid4().hex
        async with root_engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = root_engine.execution_options(schema_translate_map={None: schema})
    else:
        engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "writes.sqlite"))
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AdvisorWriteSession)
    tables = [m.__table__ for m in (Role, Tenant, User, TenantModule, Grant,
                                  GeoProject, GeoVisibilityPatrolSettings, GeoOptimizationBusiness,
                                  GeoOptimizationPeriod)]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    async with factory() as s:
        s.add_all([Role(id=1, name="顾问", is_system=False,
                       permissions={"geo.assets": "edit", "geo.content": "edit"}),
                   Role(id=2, name="管理员", is_system=True, permissions={"settings.accounts": "edit"}),
                   Role(id=3, name="客户", is_system=False, permissions={"geo.content": "edit"})])
        await s.flush()
        for tid in (10, 20, 30):
            s.add(Tenant(id=tid, name="unchanged"))
        await s.flush()
        for tid in (10, 20, 30):
            s.add(TenantModule(id=tid, tenant_id=tid, module_code="geo", status="active"))
        s.add_all([User(id=1, username="advisor", password_hash="unused", role_id=1, tenant_id=10, is_active=True),
                   User(id=2, username="admin", password_hash="unused", role_id=2, is_active=True),
                   User(id=3, username="customer", password_hash="unused", role_id=3, tenant_id=10, is_active=True)])
        await s.flush()
        s.add_all([Grant(id=101, user_id=1, tenant_id=10, grant_source="backfill", granted_at=datetime(2026, 1, 1)),
                   Grant(id=102, user_id=1, tenant_id=20, grant_source="backfill", granted_at=datetime(2026, 1, 1))])
        await s.commit()

    policy = ModuleType("app.security.advisor_write_objects")
    calls = []
    async def objects(s, ctx, request, body, rule):
        calls.append("objects")
        if "tenant_id" in body:
            ctx.ensure_tenant(body["tenant_id"])
    async def assignment(*_args):
        calls.append("assignment")
        if state.get("unassigned"):
            deny(403, "ADVISOR_ASSIGNMENT_REQUIRED", "unassigned test project")
    policy.check_write_objects = objects
    policy.ensure_advisor_assignment = assignment
    monkeypatch.setitem(sys.modules, policy.__name__, policy)
    app = FastAPI()
    state = {}
    async def dependency():
        async with factory() as s:
            yield s
    app.dependency_overrides[get_session] = dependency

    async def endpoint(request: Request, ctx=Depends(require_auth), s=Depends(get_session)):
        body = await request.json()  # proves guard body caching preserves reread
        row = await s.get(Tenant, 10)
        row.name = "committed"
        race = state.pop("race", None)
        if race is not None:
            async with factory() as other:
                await other.execute(race)
                await other.commit()
        await s.commit()
        return {"body": body, "scoped": hasattr(request.state, "advisor_scoped_write")}
    for method, path in WRITE_ROUTES:
        app.add_api_route(path, endpoint, methods=[method])
    app.add_api_route("/api/v1/geo/content-tasks/{task_id}/not-reviewed", endpoint, methods=["POST"])
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            async def request(path, body, *, method="POST", auth=None, query="tenant_id=10"):
                return await client.request(method, "/api/v1/geo" + path + "?" + query,
                    headers={"Authorization": "Bearer " + (auth or token())},
                    **({"content": b"null"} if body is None else {"json": body}))
            yield request, factory, state, calls
    finally:
        if schema:
            assert schema.startswith("geo_a_write_") and len(schema) == 44
            async with root_engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


def test_switch_is_default_off():
    assert Settings.model_fields["advisor_scoped_content_writes_enabled"].default is False


@pytest.mark.parametrize("old_flag", [False, True])
def test_disabled_switch_ignores_old_flag(tmp_path, monkeypatch, old_flag):
    async def run():
        monkeypatch.setattr(get_settings(), "advisor_high_risk_writes_enabled", old_flag)
        async with sandbox(tmp_path, monkeypatch, enabled=False) as (request, _, _, calls):
            r = await request("/facts", {"tenant_id": 10})
            assert r.status_code == 403 and r.json()["detail"]["code"] == "ADVISOR_HIGH_RISK_WRITES_DISABLED"
            assert not calls
    asyncio.run(run())


@pytest.mark.parametrize("key", list(WRITE_ROUTES))
def test_every_exact_rule_calls_both_contracts_and_commit_rechecks(tmp_path, monkeypatch, key):
    async def run():
        method, template = key
        rule = WRITE_ROUTES[key]
        path = template.removeprefix("/api/v1/geo").replace("{fact_id}", "1").replace("{prompt_id}", "1")
        path = path.replace("{unit_id}", "1").replace("{business_id}", "1").replace("{task_id}", "1").replace("{channel}", "website")
        body = {"tenant_id": 10} if "tenant_id" in rule.fields else {}
        if template == "/api/v1/geo/content-imports/create-task":
            body["source_type"] = "paste"
        if template.endswith("/generate"):
            body = None
        if template.endswith("/article"):
            body["expected_article_id"] = None
        async with sandbox(tmp_path, monkeypatch) as (request, factory, _, calls):
            r = await request(path, body, method=method)
            assert r.status_code == 200, r.text
            assert r.json() == {"body": body, "scoped": True}
            assert calls == ["objects", "objects", "assignment", "objects", "assignment"]
            async with factory() as s:
                assert (await s.get(Tenant, 10)).name == "committed"
    asyncio.run(run())


@pytest.mark.parametrize("body", [{"status": "published"}, {"owner_user_id": 1},
    {"brief": {"nested": {"owner_user_id": 1}}}, {"brief": {"notes": {"fact_id": 30}}},
    {"outline": {"verified": True}}, {"unexpected": True}])
def test_forbidden_fields_stop_before_assignment_or_commit(tmp_path, monkeypatch, body):
    async def run():
        async with sandbox(tmp_path, monkeypatch) as (request, factory, _, calls):
            r = await request("/content-tasks/1", body, method="PATCH")
            assert r.status_code == 403 and r.json()["detail"]["code"] == "ADVISOR_WRITE_FIELD_FORBIDDEN"
            assert calls == ["objects"] * (2 if "brief" in body else 1)
            async with factory() as s:
                assert (await s.get(Tenant, 10)).name == "unchanged"
    asyncio.run(run())


@pytest.mark.parametrize("query", ["tenant_id=20", "tenant_id=30", "tenant_id=10&tenant_id=20", "", "tenant_id=10&use_llm=true"])
def test_selected_customer_and_query_action_boundaries(tmp_path, monkeypatch, query):
    async def run():
        async with sandbox(tmp_path, monkeypatch) as (request, _, _, calls):
            assert (await request("/facts", {"tenant_id": 10}, query=query)).status_code == 403
            assert "assignment" not in calls
    asyncio.run(run())


@pytest.mark.parametrize("race", [
    update(Grant).where(Grant.id == 101).values(revoked_at=datetime.now(timezone.utc),
                                             revoked_by=2, revoke_reason="admin_uncheck"),
    update(User).where(User.id == 1).values(is_active=False),
    update(Role).where(Role.id == 1).values(permissions={"geo.assets": "edit", "geo.content": "view"}),
    update(User).where(User.id == 1).values(role_id=3),
])
def test_real_commit_hook_reloads_authority_and_rolls_back(tmp_path, monkeypatch, race):
    async def run():
        async with sandbox(tmp_path, monkeypatch) as (request, factory, state, _):
            state["race"] = race
            r = await request("/facts", {"tenant_id": 10})
            assert r.status_code in {401, 403}, r.text
            async with factory() as s:
                assert (await s.get(Tenant, 10)).name == "unchanged"
    asyncio.run(run())


def test_unlisted_missing_assignment_and_native_contexts(tmp_path, monkeypatch):
    async def run():
        async with sandbox(tmp_path, monkeypatch) as (request, _, state, calls):
            r = await request("/content-tasks/1/not-reviewed", {})
            assert r.status_code == 403 and not calls
            state["unassigned"] = True
            assert (await request("/facts", {"tenant_id": 10})).status_code == 403
            for uid in (2, 3):
                r = await request("/facts", {"tenant_id": 10}, auth=legacy(uid))
                assert r.status_code == 200 and not r.json()["scoped"], r.text
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["patrol", "plan", "period"])
def test_enabled_execution_chain_denied_without_committing(tmp_path, monkeypatch, kind):
    async def run():
        async with sandbox(tmp_path, monkeypatch) as (request, factory, _, _):
            async with factory() as s:
                if kind == "patrol":
                    s.add(GeoVisibilityPatrolSettings(tenant_id=10, enabled=True))
                elif kind == "plan":
                    s.add(GeoProject(id=1, tenant_id=10, tenant_module_id=10, name="p", primary_domain="test",
                        canonical_domain="test", project_settings={"geo_service_plan": {"enabled": True}}))
                else:
                    s.add(GeoOptimizationPeriod(id=1, tenant_id=10, name="p", status="active",
                        starts_at=datetime(2026, 1, 1), ends_at=datetime(2027, 1, 1)))
                await s.commit()
            r = await request("/facts", {"tenant_id": 10})
            assert r.status_code == 403 and r.json()["detail"]["code"] == "ADVISOR_EXECUTION_CHAIN_ACTIVE"
            async with factory() as s:
                assert (await s.get(Tenant, 10)).name == "unchanged"
    asyncio.run(run())


def test_route_resolution_and_required_version_fields():
    request = SimpleNamespace(method="POST", scope={}, url=SimpleNamespace(path="/api/v1/geo/facts"))
    assert match_write_rule(request) is None
    article = WRITE_ROUTES[("PUT", "/api/v1/geo/content-tasks/{task_id}/article")]
    with pytest.raises(HTTPException):
        check_write_fields(article, {"title": "title", "body_markdown": "body"})
    check_write_fields(article, {"title": "title", "body_markdown": "body", "expected_article_id": None})
    fact = WRITE_ROUTES[("POST", "/api/v1/geo/facts")]
    for body in ({"trust_level": "verified"}, {"meta": {"public_use": {"allowed": True}}}):
        with pytest.raises(HTTPException):
            check_write_fields(fact, body)


@pytest.mark.parametrize("status", ["generating", "ready", "published", "archived", "review"])
def test_task_states_cannot_be_changed_by_manual_advisor_writes(status):
    async def run():
        ctx = SimpleNamespace(advisor_scope=AdvisorScope(frozenset({10}), 10, 101))
        with pytest.raises(HTTPException) as exc:
            await lock_manual_task(None, ctx, SimpleNamespace(status=status), already_locked=True)
        assert exc.value.status_code == 403
    asyncio.run(run())


def test_object_refresh_at_commit_preserves_edits_and_assignment_failure_rolls_back(tmp_path, monkeypatch):
    async def run():
        async with sandbox(tmp_path, monkeypatch) as (request, factory, _, _):
            policy = sys.modules["app.security.advisor_write_objects"]
            async def fresh_object(s, *_args):
                await s.scalar(select(Tenant).where(Tenant.id == 10).execution_options(populate_existing=True))
            policy.check_write_objects = fresh_object
            assert (await request("/facts", {"tenant_id": 10})).status_code == 200
            async with factory() as s:
                assert (await s.get(Tenant, 10)).name == "committed"
                await s.execute(update(Tenant).where(Tenant.id == 10).values(name="unchanged"))
                await s.commit()
            calls = 0
            async def removed_assignment(*_args):
                nonlocal calls
                calls += 1
                if calls == 2:
                    deny(403, "ADVISOR_ASSIGNMENT_REQUIRED", "removed before commit")
            policy.ensure_advisor_assignment = removed_assignment
            assert (await request("/facts", {"tenant_id": 10})).status_code == 403
            async with factory() as s:
                assert (await s.get(Tenant, 10)).name == "unchanged"
    asyncio.run(run())


def test_missing_b_integration_fails_closed(tmp_path, monkeypatch):
    async def run():
        async with sandbox(tmp_path, monkeypatch) as (request, _, _, _):
            monkeypatch.setitem(sys.modules, "app.security.advisor_write_objects", None)
            r = await request("/facts", {"tenant_id": 10})
            assert r.status_code == 403 and r.json()["detail"]["code"] == "ADVISOR_OBJECT_UNAVAILABLE"
    asyncio.run(run())


@pytest.mark.skipif(not os.environ.get("GEO_TEST_POSTGRES_URL"),
                    reason="requires the explicitly owned local PostgreSQL cluster")
def test_postgres_writer_waits_for_central_user_lock_then_observes_revoke(tmp_path, monkeypatch):
    monkeypatch.setenv("GEO_ADVISOR_WRITE_LOCAL_POSTGRES", "yes")
    async def run():
        import app.security.advisor_write_commit as commit_policy
        async with sandbox(tmp_path, monkeypatch) as (request, factory, _, _):
            entered = asyncio.Event()
            original = commit_policy.recheck_advisor_before_commit
            async def observed(s, ctx):
                entered.set()
                await original(s, ctx)
            monkeypatch.setattr(commit_policy, "recheck_advisor_before_commit", observed)
            async with factory() as revoker:
                await revoker.scalar(select(User.id).where(User.id == 1).with_for_update())
                await revoker.execute(update(Grant).where(Grant.id == 101).values(
                    revoked_at=datetime.now(timezone.utc), revoked_by=2, revoke_reason="admin_uncheck"))
                pending = asyncio.create_task(request("/facts", {"tenant_id": 10}))
                await asyncio.wait_for(entered.wait(), timeout=5)
                assert not pending.done()
                await revoker.commit()
                response = await asyncio.wait_for(pending, timeout=5)
            assert response.status_code == 401
            assert response.json()["detail"]["code"] == "ADVISOR_GRANT_REVOKED"
            async with factory() as s:
                assert (await s.get(Tenant, 10)).name == "unchanged"
    asyncio.run(run())
