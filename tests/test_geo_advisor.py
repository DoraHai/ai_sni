"""Real HTTP/SQL isolation regressions using only per-test local SQLite files."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import jwt
import pytest
from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.database import Base, get_session
from app.models import GeoAsyncJob, GeoAuditRun, GeoMediaPlacement, GeoProject, Role, Tenant, TenantModule, User
from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
from app.security.auth import JWT_ALG, _jwt_secret, require_auth
from app.security.geo_advisor_delivery import AdvisorDeliveryMiddleware


@compiles(JSONB, "sqlite")
def _sqlite_json(_type, _compiler, **_kw):
    return "JSON"


def token(uid=1, tid=10, gid=101, **overrides):
    now = int(datetime.now(timezone.utc).timestamp())
    claims = dict(sub=str(uid), exp=now + 600, iat=now,
                  scope_kind="advisor_tenant", aud="advisor-business",
                  tid=tid, gid=gid, auth_exp=now + 600)
    claims.update(overrides)
    return jwt.encode(claims, _jwt_secret(), algorithm=JWT_ALG)


def legacy(uid):
    return jwt.encode({"sub": str(uid), "exp": int(datetime.now(timezone.utc).timestamp()) + 600},
                      _jwt_secret(), algorithm=JWT_ALG)


@pytest.mark.parametrize("settings_key", ["settings.customers", "settings.future"])
@pytest.mark.parametrize("level, expected", [("edit", False), ("view", True)])
def test_shared_predicate_excludes_raw_settings_edits_without_changing_geo_rbac(settings_key, level, expected):
    from app.permissions import MENU_KEYS
    from app.security.advisor_scope import is_advisor
    role = SimpleNamespace(name="客户管理员", is_system=False, permissions={
        "geo.assets": "edit", "geo.content": "edit", settings_key: level})
    assert is_advisor(role) is expected
    assert settings_key not in MENU_KEYS


@asynccontextmanager
async def sandbox(tmp_path, monkeypatch, *, with_grants=True):
    from app.geo.content.routes import router, geo_read_session
    from app.geo.project_routes import geo_projects_router
    from app.geo.routes import router as diagnosis_router
    import app.geo.tenant_scope as entitlement
    import app.database as database

    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "geo-advisor.sqlite"))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tables = [Role.__table__, Tenant.__table__, User.__table__, TenantModule.__table__,
              GeoProject.__table__, GeoAsyncJob.__table__, GeoAuditRun.__table__, GeoMediaPlacement.__table__]
    if with_grants:
        tables.append(Grant.__table__)
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    async with factory() as s:
        s.add_all([Role(id=1, name="顾问", is_system=False, permissions={"geo.assets": "edit", "geo.content": "edit"}),
                   Role(id=2, name="管理员", is_system=True, permissions={"geo.assets": "edit", "geo.content": "edit", "settings.accounts": "edit"}),
                   Role(id=3, name="客户", is_system=False, permissions={"geo.assets": "view", "geo.content": "view"})])
        for tid in (10, 20, 30):
            s.add(Tenant(id=tid, name=f"客户{tid}"))
            s.add(TenantModule(id=tid, tenant_id=tid, module_code="geo", status="active"))
            s.add(GeoProject(id=tid, tenant_id=tid, tenant_module_id=tid, name=f"项目{tid}",
                             primary_domain=f"{tid}.example", canonical_domain=f"{tid}.example",
                             project_settings={"geo_service_plan": {"advisor_user_id": 1}}))
            s.add(GeoAsyncJob(id=tid, tenant_id=tid, kind="generate_article", status="pending", created_by=1))
        s.add_all([User(id=1, username="advisor", role_id=1, tenant_id=10, is_active=True, password_hash="unused"),
                   User(id=2, username="admin", role_id=2, tenant_id=None, is_active=True, password_hash="unused"),
                   User(id=3, username="customer", role_id=3, tenant_id=10, is_active=True, password_hash="unused")])
        if with_grants:
            s.add_all([Grant(id=101, user_id=1, tenant_id=10, grant_source="backfill"),
                       Grant(id=102, user_id=1, tenant_id=20, grant_source="backfill")])
        await s.commit()

    async def session():
        async with factory() as s:
            yield s

    # The entitlement's PostgreSQL demo JSON query is covered by existing GEO
    # regressions; this fixture is production-only. Module checks remain real SQL.
    async def production(*_a, **_kw):
        return SimpleNamespace(is_demo=False, read_only=False)

    monkeypatch.setattr(entitlement, "ensure_geo_entitlement", production)
    monkeypatch.setattr(database, "async_session_factory", factory)
    app = FastAPI()
    app.add_middleware(AdvisorDeliveryMiddleware)
    app.include_router(router, prefix="/api/v1/geo")
    app.include_router(geo_projects_router)
    app.include_router(diagnosis_router)
    # Registered unknown route must stay closed even with a valid context.
    from fastapi import Depends
    @app.get("/api/v1/geo/not-reviewed")
    async def unknown(ctx=Depends(require_auth)):
        return {"leak": True}
    app.dependency_overrides[get_session] = session
    app.dependency_overrides[geo_read_session] = session
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        async def request(path, *, auth=None, method="GET", **kwargs):
            return await client.request(method, "/api/v1/geo" + path,
                                        headers={"Authorization": "Bearer " + (auth or token())}, **kwargs)
        try:
            yield request, factory
        finally:
            await engine.dispose()


@pytest.mark.parametrize("path", ["/channel-blueprint", "/structure-scan/latest"])
def test_content_reads_keep_selected_grants_and_native_scope(tmp_path, monkeypatch, path):
    async def run():
        from app.geo.content.routes import blueprint_payload
        channel = blueprint_payload()["all_channels"][0]["channel_key"]
        async with sandbox(tmp_path, monkeypatch) as (request, factory):
            async with factory() as s:
                for tid in (10, 20, 30):
                    s.add(GeoAuditRun(id=tid, tenant_id=tid, url=f"https://{tid}.example",
                                     snapshot={"kind": "website_structure", "structure": {"score": tid}}))
                    s.add(GeoMediaPlacement(id=tid, tenant_id=tid, name=f"媒体{tid}", channel_key=channel))
                await s.commit()
            for tid, gid in [(10, 101), (20, 102)]:
                response = await request(f"{path}?tenant_id={tid}", auth=token(tid=tid, gid=gid))
                assert response.status_code == 200, response.text
                assert response.headers["cache-control"] == "private, no-store"
                payload = response.json()
                if path == "/structure-scan/latest":
                    assert payload["report"]["audit_id"] == tid
                    assert payload["report"]["score"] == tid
                else:
                    assert {c["placement_id"] for c in payload["all_channels"] if c["placement_id"]} == {tid}
            # Customer 20 is granted but not selected; 30 has no grant.
            for query in ("tenant_id=20", "tenant_id=30", "tenant_id=10&tenant_id=30", ""):
                assert (await request(f"{path}?{query}")).status_code == 403
            assert (await request(f"{path}?tenant_id=30", auth=token(tid=30, gid=999))).status_code == 401
            identity = token(scope_kind="advisor_identity", aud="advisor-session")
            for auth in (identity, legacy(1)):
                response = await request(f"{path}?tenant_id=10", auth=auth)
                assert response.status_code == 409
                assert response.json()["detail"]["code"] == "ADVISOR_TENANT_SELECTION_REQUIRED"
            # Ordinary customers retain tenant isolation; administrators remain unbound.
            assert (await request(f"{path}?tenant_id=10", auth=legacy(3))).status_code == 200
            assert (await request(f"{path}?tenant_id=20", auth=legacy(3))).status_code == 403
            assert (await request(f"{path}?tenant_id=30", auth=legacy(2))).status_code == 200
            async with factory() as s:
                await s.execute(update(Grant).where(Grant.id == 101).values(
                    revoked_at=datetime.now(timezone.utc), revoked_by=2, revoke_reason="admin_uncheck"))
                await s.commit()
            assert (await request(f"{path}?tenant_id=10")).status_code == 401
    asyncio.run(run())


@pytest.mark.parametrize("enabled", [False, True])
def test_content_read_fix_keeps_high_risk_posts_closed(tmp_path, monkeypatch, enabled):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "advisor_scoped_content_writes_enabled", enabled)
    async def run():
        async with sandbox(tmp_path, monkeypatch) as (request, _factory):
            for path in ("/structure-scan", "/action-tickets"):
                response = await request(f"{path}?tenant_id=10", method="POST", json={"title": "test"})
                assert response.status_code == 403, response.text
                assert response.json()["detail"]["code"] == "ADVISOR_HIGH_RISK_WRITES_DISABLED"
    asyncio.run(run())


@pytest.mark.parametrize("path", ["/api/v1/geo/channel-blueprint", "/api/v1/geo/structure-scan/latest"])
def test_content_read_mapping_is_exact_and_get_only(path):
    from app.security.auth import AuthContext, _required, require_scoped_auth
    from starlette.requests import Request
    assert _required(path, "GET") == ({"geo.content"}, False)
    for method in ("HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"):
        assert _required(path, method) == ({"geo.diagnosis"}, False)
    for suffix in ("/", "/extra", "-extra"):
        assert _required(path + suffix, "GET") == ({"geo.diagnosis"}, False)
    # Existing diagnosis-only POST access for non-advisors keeps its menu contract.
    ctx = AuthContext(2, "native", "管理员", None, {"geo.diagnosis": "view"})
    for write_path in ("/api/v1/geo/structure-scan", "/api/v1/geo/action-tickets"):
        assert _required(write_path, "POST") == ({"geo.diagnosis"}, False)
        request = Request({"type": "http", "method": "POST", "path": write_path,
                           "query_string": b"", "headers": []})
        assert asyncio.run(require_scoped_auth(request, ctx)) is ctx


def test_two_grants_context_and_job_idor(tmp_path, monkeypatch):
    async def run():
        async with sandbox(tmp_path, monkeypatch) as (request, _factory):
            for tid, gid in [(10, 101), (20, 102)]:
                response = await request(f"/projects?tenant_id={tid}", auth=token(tid=tid, gid=gid))
                assert response.status_code == 200, response.text
                assert [p["tenant_id"] for p in response.json()["projects"]] == [tid]
                assert response.headers["cache-control"] == "private, no-store"
            for path in ["/projects?tenant_id=30", "/projects?tenant_id=20",
                         "/projects?tenant_id=10&tenant_id=30", "/projects?tenant_id=true",
                         "/async-jobs/30?tenant_id=10", "/async-jobs/20?tenant_id=10",
                         "/async-jobs?tenant_id=30", "/async-jobs?tenant_id=10&project_id=30"]:
                assert (await request(path)).status_code in {403, 422}, path
            assert (await request("/async-jobs/10?tenant_id=10")).status_code == 200
            response = await request("/async-jobs?tenant_id=10")
            assert response.status_code == 200, response.text
            assert [j["id"] for j in response.json()["items"]] == [10]
            assert (await request("/not-reviewed?tenant_id=10")).status_code == 403
            assert (await request("/projects")).status_code == 403
    asyncio.run(run())


def test_revocation_regrant_empty_role_and_account_changes(tmp_path, monkeypatch):
    async def run():
        async with sandbox(tmp_path, monkeypatch) as (request, factory):
            async def mutate(model, ident, **values):
                async with factory() as s:
                    await s.execute(update(model).where(model.id == ident).values(**values))
                    await s.commit()
            await mutate(Grant, 101, revoked_at=datetime.now(timezone.utc), revoked_by=2, revoke_reason="admin_uncheck")
            r = await request("/projects?tenant_id=10")
            assert r.status_code == 401 and r.json()["detail"]["code"] == "ADVISOR_GRANT_REVOKED"
            async with factory() as s:
                s.add(Grant(id=103, user_id=1, tenant_id=10, granted_by=2, grant_source="admin"))
                await s.commit()
            assert (await request("/projects?tenant_id=10")).status_code == 401
            assert (await request("/projects?tenant_id=10", auth=token(gid=103))).status_code == 200
            await mutate(User, 1, locked_until=datetime.now() + timedelta(hours=1))
            assert (await request("/projects?tenant_id=10", auth=token(gid=103))).status_code == 401
            await mutate(User, 1, locked_until=None, role_id=3)
            assert (await request("/projects?tenant_id=10", auth=legacy(1))).status_code == 403
            await mutate(User, 1, role_id=1, tenant_id=None)
            for gid in (102, 103):
                await mutate(Grant, gid, revoked_at=datetime.now(timezone.utc), revoked_by=2, revoke_reason="admin_uncheck")
            r = await request("/projects?tenant_id=10", auth=token(scope_kind="advisor_identity", aud="advisor-session"))
            assert r.status_code == 403 and r.json()["detail"]["code"] == "ADVISOR_NO_TENANT"
    asyncio.run(run())


@pytest.mark.parametrize("with_grants", [False, True])
def test_missing_table_and_native_regressions(tmp_path, monkeypatch, with_grants):
    async def run():
        async with sandbox(tmp_path, monkeypatch, with_grants=with_grants) as (request, _factory):
            assert (await request("/projects?tenant_id=30", auth=legacy(2))).status_code == 200
            assert (await request("/projects?tenant_id=10", auth=legacy(3))).status_code == 200
            assert (await request("/projects?tenant_id=20", auth=legacy(3))).status_code == 403
            assert (await request("/projects?tenant_id=30", auth=legacy(2), method="GET")).status_code == 200
            if not with_grants:
                r = await request("/projects?tenant_id=10")
                assert r.status_code == 503 and r.json()["detail"]["code"] == "ADVISOR_GRANTS_UNAVAILABLE"
    asyncio.run(run())


@pytest.mark.parametrize("changes", [dict(aud="advisor-session"), dict(gid=True), dict(tid=True),
    dict(scope_kind="unknown"), dict(auth_exp=1), dict(exp=True), dict(sub="false"), dict(gid=999)])
def test_invalid_claims(tmp_path, monkeypatch, changes):
    async def run():
        async with sandbox(tmp_path, monkeypatch) as (request, _factory):
            assert (await request("/projects?tenant_id=10", auth=token(**changes))).status_code == 401
    asyncio.run(run())


def test_no_dispatch_identity_old_tokens_or_legacy_switch(tmp_path, monkeypatch):
    async def run():
        async with sandbox(tmp_path, monkeypatch) as (request, factory):
            for path in ["/async-jobs/30/cancel?tenant_id=10", "/async-jobs/10/cancel?tenant_id=10",
                         "/content-tasks/10/generate?tenant_id=10", "/projects?tenant_id=10"]:
                r = await request(path, method="POST", json={"tenant_id": 10})
                assert r.status_code == 403, r.text
            assert (await request("/projects?tenant_id=10", auth=legacy(1))).status_code == 409
            identity = token(scope_kind="advisor_identity", aud="advisor-session")
            assert (await request("/projects?tenant_id=10", auth=identity)).status_code == 409
            assert (await request("/projects?tenant_id=10", auth=token(via="advisor_switch"))).status_code == 401
            async with factory() as s:
                assert (await s.get(GeoAsyncJob, 10)).status == "pending"
    asyncio.run(run())


def test_revoke_between_query_and_delivery(tmp_path, monkeypatch):
    async def run():
        from fastapi import HTTPException
        from app.security.geo_advisor_delivery import recheck_delivery
        async with sandbox(tmp_path, monkeypatch) as (_request, factory):
            claims = jwt.decode(token(), _jwt_secret(), algorithms=[JWT_ALG], audience="advisor-business")
            await recheck_delivery(1, claims, 10)
            async with factory() as s:
                await s.execute(update(Grant).where(Grant.id == 101).values(
                    revoked_at=datetime.now(timezone.utc), revoked_by=2, revoke_reason="admin_uncheck"))
                await s.commit()
            with pytest.raises(HTTPException) as denied:
                await recheck_delivery(1, claims, 10)
            assert denied.value.status_code == 401
            messages = []
            async def app(scope, receive, send):
                scope["geo_advisor_delivery"] = (1, claims, 10)
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": b"must not escape"})
            async def send(message):
                messages.append(message)
            await AdvisorDeliveryMiddleware(app)({"type": "http"}, None, send)
            assert messages[0]["status"] == 401
            assert all(b"must not escape" not in m.get("body", b"") for m in messages)
    asyncio.run(run())


def test_permission_failure_closed_for_advisor_only(tmp_path, monkeypatch):
    async def run():
        from app.security import geo_advisor
        from app.security.advisor_scope import deny
        async with sandbox(tmp_path, monkeypatch) as (request, _factory):
            async def unavailable(*_a):
                deny(503, "ADVISOR_GRANTS_UNAVAILABLE", "fixture permission denied")
            monkeypatch.setattr(geo_advisor, "read_grants", unavailable)
            assert (await request("/projects?tenant_id=10")).status_code == 503
            assert (await request("/projects?tenant_id=10", auth=legacy(3))).status_code == 200
            assert (await request("/projects?tenant_id=30", auth=legacy(2))).status_code == 200
    asyncio.run(run())


@pytest.mark.parametrize("revoked", [False, True])
def test_raw_settings_edit_does_not_release_grant_history(tmp_path, monkeypatch, revoked):
    async def run():
        async with sandbox(tmp_path, monkeypatch) as (request, factory):
            async with factory() as s:
                await s.execute(update(Role).where(Role.id == 1).values(permissions={
                    "geo.assets": "edit", "geo.content": "edit", "settings.future": "edit"}))
                await s.execute(update(User).where(User.id == 1).values(tenant_id=None))
                if revoked:
                    await s.execute(update(Grant).where(Grant.user_id == 1).values(
                        revoked_at=datetime.now(timezone.utc), revoked_by=2, revoke_reason="role_changed"))
                await s.commit()
            for auth in (legacy(1), token()):
                response = await request("/projects?tenant_id=30", auth=auth)
                assert response.status_code == 403, response.text
                assert response.json()["detail"]["code"] == "ADVISOR_ROLE_CHANGED"
    asyncio.run(run())


@pytest.mark.parametrize("with_grants", [False, True])
def test_raw_settings_edit_native_account_keeps_single_tenant_scope(tmp_path, monkeypatch, with_grants):
    async def run():
        async with sandbox(tmp_path, monkeypatch, with_grants=with_grants) as (request, factory):
            async with factory() as s:
                await s.execute(update(Role).where(Role.id == 3).values(permissions={
                    "geo.assets": "edit", "geo.content": "edit", "settings.future": "edit"}))
                await s.commit()
            assert (await request("/projects?tenant_id=10", auth=legacy(3))).status_code == 200
            assert (await request("/projects?tenant_id=30", auth=legacy(3))).status_code == 403
    asyncio.run(run())
