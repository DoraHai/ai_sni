"""Real per-request SQL authorization against a temporary local SQLite DB."""
import asyncio
from datetime import date, datetime, timedelta, timezone

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import auth, users, roles
from app.config import get_settings
from app.database import Base, get_session
from app.models import Role, User, Tenant, TenantModule, Keyword
from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
from app.security.auth import require_auth, require_scoped_auth, issue_token, _jwt_secret, JWT_ALG
from app.security.advisor_scope import is_advisor


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(BigInteger, "sqlite")
def _bigint_sqlite(type_, compiler, **kw):
    return "INTEGER"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db(tmp_path, monkeypatch):
    settings = get_settings().model_copy(update={"advisor_multi_tenant_enabled": True,
        "advisor_legacy_account_switch_enabled": False, "advisor_high_risk_writes_enabled": False})
    for module in (auth,):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr("app.security.advisor_switch.get_settings", lambda: settings)
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "advisor.db"), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async def seed():
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=[
                Role.__table__, User.__table__, Tenant.__table__, TenantModule.__table__,
                Grant.__table__, Keyword.__table__]))
        async with factory() as s:
            s.add_all([Role(id=1, name="顾问测试", is_system=False, permissions={
                "seo.site": "edit", "seo.content": "edit", "optimize.keywords": "edit", "delivery.report": "view"}),
                Role(id=2, name="管理员", is_system=True, permissions={}),
                Role(id=3, name="客户测试", is_system=False, permissions={"optimize.keywords": "view"}),
                User(id=1, username="advisor", role_id=1, tenant_id=10, is_active=True, password_hash="unused"),
                User(id=2, username="admin", role_id=2, tenant_id=None, is_active=True, password_hash="unused"),
                User(id=3, username="customer", role_id=3, tenant_id=10, is_active=True, password_hash="unused"),
                Tenant(id=10, name="A"), Tenant(id=20, name="B"), Tenant(id=30, name="C")])
            for tid in (10, 20, 30):
                s.add(TenantModule(tenant_id=tid, module_code="sem", status="active"))
            s.add_all([Grant(id=101, user_id=1, tenant_id=10, grant_source="backfill"),
                       Grant(id=102, user_id=1, tenant_id=20, grant_source="admin", granted_by=2),
                       Keyword(id=201, keyword_id=301, tenant_id=10),
                       Keyword(id=202, keyword_id=302, tenant_id=30)])
            await s.commit()
    run(seed())
    async def session():
        async with factory() as s:
            yield s
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(roles.router)
    @app.get("/api/v1/keywords")
    async def business(tenant_id: int, ctx=Depends(require_auth)):
        return {"tenant_id": ctx.tenant_id}
    @app.get("/api/v1/keywords/{keyword_id}")
    async def obj(keyword_id: int, tenant_id: int, ctx=Depends(require_auth)):
        return {"id": keyword_id}
    @app.post("/api/v1/keywords/pause-batch")
    async def write(ctx=Depends(require_scoped_auth)):
        return {"unsafe": True}
    @app.get("/unregistered")
    async def unknown(ctx=Depends(require_auth)):
        return {"unsafe": True}
    app.dependency_overrides[get_session] = session
    with TestClient(app) as client:
        yield client, factory, settings
    run(engine.dispose())


def token(*, advisor=True, tid=None, gid=None, user_id=1):
    return issue_token(User(id=user_id), advisor=advisor, tenant_id=tid, grant_id=gid,
                       auth_exp=int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()))


def headers(value):
    return {"Authorization": "Bearer " + value}


def test_predicate_excludes_admin_and_preserves_permission_combinations():
    assert is_advisor(Role(name="anything", is_system=False,
                           permissions={"seo.site": "edit", "seo.content": "edit"}))
    assert not is_advisor(Role(name="管理员", is_system=True,
                              permissions={"seo.site": "edit", "seo.content": "edit"}))
    assert not is_advisor(Role(name="anything", is_system=False,
                              permissions={"seo.site": "edit", "seo.content": "edit", "settings.accounts": "edit"}))


@pytest.mark.parametrize("revoked", [False, True])
def test_raw_settings_exclusion_keeps_grant_history_restricted(db, revoked):
    client, factory, _ = db
    async def mutate():
        async with factory() as s:
            role = await s.get(Role, 1)
            role.permissions = dict(role.permissions, **{"settings.future": "edit"})
            (await s.get(User, 1)).tenant_id = None
            if revoked:
                for grant in (await s.scalars(select(Grant).where(Grant.user_id == 1))).all():
                    grant.revoked_at = datetime.now(timezone.utc) + timedelta(seconds=1)
                    grant.revoked_by = 2
                    grant.revoke_reason = "admin_uncheck"
            await s.commit()
    run(mutate())
    # Even an old unscoped JWT must not turn NULL tenant into all customers.
    for value in (token(advisor=False), token(), token(tid=10, gid=101)):
        response = client.get("/api/v1/auth/me", headers=headers(value))
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "ADVISOR_ROLE_CHANGED"


def test_two_grants_identity_and_business_boundaries(db):
    client, _, _ = db
    identity = headers(token())
    assert [t["id"] for t in client.get("/api/v1/auth/tenants", headers=identity).json()["tenants"]] == [10, 20]
    assert client.get("/api/v1/keywords?tenant_id=10", headers=identity).status_code == 409
    business = headers(token(tid=10, gid=101))
    assert client.get("/api/v1/keywords?tenant_id=10", headers=business).status_code == 200
    for query in ("tenant_id=20", "tenant_id=30", "tenant_id=10&tenant_id=30"):
        assert client.get("/api/v1/keywords?" + query, headers=business).status_code == 403
    assert client.get("/unregistered", headers=business).status_code == 403
    assert client.get("/api/v1/keywords/302?tenant_id=10", headers=business).status_code == 403
    assert client.get("/api/v1/keywords/301?tenant_id=10", headers=business).status_code == 200
    assert client.post("/api/v1/keywords/pause-batch", json={"tenant_id": 10, "nested": {"tenant_id": 30}}, headers=business).status_code == 403
    assert client.post("/api/v1/keywords/pause-batch", json={"tenant_id": 10}, headers=business).status_code == 403


def test_empty_revoked_and_regranted_old_generation_never_revives(db):
    client, factory, _ = db
    old = headers(token(tid=10, gid=101))
    async def revoke():
        async with factory() as s:
            for g in (await s.scalars(select(Grant))).all():
                g.revoked_at = datetime.now(timezone.utc) + timedelta(seconds=1)
                g.revoked_by = 2
                g.revoke_reason = "admin_uncheck"
            await s.commit()
    run(revoke())
    assert client.get("/api/v1/keywords?tenant_id=10", headers=old).status_code == 401
    identity = headers(token())
    assert client.get("/api/v1/auth/tenants", headers=identity).json()["tenants"] == []
    r = client.get("/api/v1/keywords?tenant_id=10", headers=identity)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "ADVISOR_NO_TENANT"
    async def regrant():
        async with factory() as s:
            s.add(Grant(id=103, user_id=1, tenant_id=10, grant_source="admin", granted_by=2))
            await s.commit()
    run(regrant())
    assert client.get("/api/v1/keywords?tenant_id=10", headers=old).status_code == 401
    assert client.get("/api/v1/keywords?tenant_id=10", headers=headers(token(tid=10, gid=103))).status_code == 200


@pytest.mark.parametrize("change", ["locked", "disabled", "role", "module"])
def test_current_database_state_is_read_each_request(db, change):
    client, factory, _ = db
    h = headers(token(tid=10, gid=101))
    assert client.get("/api/v1/keywords?tenant_id=10", headers=h).status_code == 200
    async def mutate():
        async with factory() as s:
            u = await s.get(User, 1)
            if change == "locked":
                u.locked_until = datetime.now(timezone.utc) + timedelta(minutes=5)
            elif change == "disabled":
                u.is_active = False
            elif change == "role":
                u.role_id = 3
            else:
                m = await s.scalar(select(TenantModule).where(TenantModule.tenant_id == 10))
                m.status = "disabled"
            await s.commit()
    run(mutate())
    assert client.get("/api/v1/keywords?tenant_id=10", headers=h).status_code in (401, 403)


def test_missing_table_fails_closed_without_breaking_admin_or_fixed_customer(db):
    client, factory, _ = db
    async def drop_test_table():
        async with factory() as s:
            from sqlalchemy import text
            await s.execute(text("DROP TABLE advisor_tenant_grants"))
            await s.commit()
    run(drop_test_table())
    r = client.get("/api/v1/auth/me", headers=headers(token()))
    assert r.status_code == 503 and r.json()["detail"]["code"] == "ADVISOR_GRANTS_UNAVAILABLE"
    for uid in (2, 3):
        assert client.get("/api/v1/auth/me", headers=headers(token(advisor=False, user_id=uid))).status_code == 200


def test_default_flags_and_old_switch_tokens_are_closed(db):
    client, _, _ = db
    assert get_settings().advisor_multi_tenant_enabled is False
    assert get_settings().advisor_legacy_account_switch_enabled is False
    assert get_settings().advisor_high_risk_writes_enabled is False
    h = headers(token())
    assert client.get("/api/v1/auth/linked-accounts", headers=h).json() == {"accounts": []}
    assert client.post("/api/v1/auth/switch-account", headers=h, json={"target_user_id": 3}).status_code == 410
    legacy = issue_token(User(id=1), switch_source_id=3, root_source_id=3,
                         switch_group_id="old", auth_exp=int(datetime.now(timezone.utc).timestamp()) + 300)
    assert client.get("/api/v1/auth/me", headers=headers(legacy)).status_code == 401


def test_no_table_preserves_unrelated_role_edits_and_unbound_non_advisors(db):
    client, factory, _ = db
    async def prepare():
        async with factory() as s:
            from sqlalchemy import text
            (await s.get(User, 3)).tenant_id = None
            await s.execute(text("DROP TABLE advisor_tenant_grants"))
            await s.commit()
    run(prepare())
    admin = headers(token(advisor=False, user_id=2))
    assert client.get("/api/v1/auth/me", headers=headers(token(advisor=False, user_id=3))).status_code == 200
    assert client.patch("/api/v1/roles/3", headers=admin, json={
        "permissions": {"optimize.keywords": "edit"}}).status_code == 200
    assert client.patch("/api/v1/roles/1", headers=admin, json={
        "description": "只改说明"}).status_code == 200
    for rid, permissions in ((3, {"seo.site": "edit", "seo.content": "edit"}),
                             (1, {"seo.site": "view"})):
        response = client.patch(f"/api/v1/roles/{rid}", headers=admin,
                                json={"permissions": permissions})
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "ADVISOR_ROLE_CHANGE_FROZEN"


def test_grant_read_permission_denial_is_closed_only_for_advisors(db):
    client, factory, _ = db
    from sqlalchemy import event
    from sqlalchemy.exc import DBAPIError
    engine = factory.kw["bind"].sync_engine
    def no_grant_read(conn, cursor, statement, parameters, context, many):
        if "advisor_tenant_grants" in statement:
            raise DBAPIError("synthetic grant read", {}, PermissionError("permission denied"), False)
    event.listen(engine, "before_cursor_execute", no_grant_read)
    try:
        response = client.get("/api/v1/auth/me", headers=headers(token()))
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "ADVISOR_GRANTS_UNAVAILABLE"
        for uid in (2, 3):
            assert client.get("/api/v1/auth/me", headers=headers(token(advisor=False, user_id=uid))).status_code == 200
        assert client.patch("/api/v1/roles/3", headers=headers(token(advisor=False, user_id=2)),
                            json={"permissions": {"optimize.keywords": "edit"}}).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", no_grant_read)


@pytest.mark.parametrize("claims", [
    {"aud": "bad"}, {"scope_kind": "bad"}, {"gid": True}, {"tid": False},
    {"auth_exp": 0}, {"exp": True}, {"sub": "0"}, {"sub": "-1"},
])
def test_malformed_business_claims_are_rejected(db, claims):
    client, _, _ = db
    payload = jwt.decode(token(tid=10, gid=101), _jwt_secret(), algorithms=[JWT_ALG], audience="advisor-business")
    payload.update(claims)
    bad = jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALG)
    assert client.get("/api/v1/auth/me", headers=headers(bad)).status_code == 401
