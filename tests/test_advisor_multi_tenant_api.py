"""Account/session contract exercised via HTTP and a fresh local SQLite DB."""
import hashlib
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from test_advisor_multi_tenant import db, run, headers, token
from app.api import auth, users
from app.models import User, TenantModule
from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
from app.security.auth import _jwt_secret, JWT_ALG, hash_password


def admin():
    return headers(token(advisor=False, user_id=2))


def detail(client, uid=1):
    response = client.get(f"/api/v1/users/{uid}", headers=admin())
    assert response.status_code == 200, response.text
    return response.json()


def save(client, ids, default, version=None):
    payload = {"tenant_ids": ids, "default_tenant_id": default}
    if version is not None:
        payload["expected_grants_version"] = version
    return client.patch("/api/v1/users/1", headers=admin(), json=payload)


def test_versions_account_list_detail_missing_stale_and_default_only(db):
    client, factory, _ = db
    expected = hashlib.sha256(b"v1|10|101,102").hexdigest()[:16]
    first = detail(client)
    assert first["is_advisor"] and first["tenant_ids"] == [10, 20]
    assert first["default_tenant_id"] == 10 and first["grants_version"] == expected
    listed = client.get("/api/v1/users", headers=admin()).json()["users"]
    assert listed[0]["grants_version"] == expected
    assert listed[1]["grants_version"] is None and listed[1]["tenant_ids"] == []
    r = save(client, [10, 20], 20)
    assert r.status_code == 428 and r.json()["detail"]["code"] == "ADVISOR_GRANTS_VERSION_REQUIRED"
    r = client.patch("/api/v1/users/1", headers=admin(), json={
        "default_tenant_id": 20, "expected_grants_version": expected})
    assert r.status_code == 200 and r.json()["grants_version"] != expected
    assert r.json()["default_tenant_id"] == 20
    r = save(client, [10], 10, expected)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ADVISOR_GRANTS_CONFLICT"
    assert detail(client)["tenant_ids"] == [10, 20]
    r = client.patch("/api/v1/users/1", headers=admin(), json={"display_name": "仅改名字"})
    assert r.status_code == 200
    async def count():
        async with factory() as s:
            return len((await s.scalars(select(Grant))).all())
    assert run(count()) == 2


def test_atomic_revoke_regrant_via_api_never_revives_old_credentials(db):
    client, factory, _ = db
    identity = headers(token())
    chosen = client.post("/api/v1/auth/select-tenant", headers=identity, json={"tenant_id": 10})
    assert chosen.status_code == 200
    old = headers(chosen.json()["access_token"])
    assert client.get("/api/v1/keywords?tenant_id=10", headers=old).status_code == 200
    r = save(client, [20], 20, detail(client)["grants_version"])
    assert r.status_code == 200
    assert client.get("/api/v1/keywords?tenant_id=10", headers=old).status_code == 401
    assert client.post("/api/v1/auth/select-tenant", headers=old, json={"tenant_id": 20}).status_code == 401
    r = save(client, [10, 20, 10], 20, r.json()["grants_version"])
    assert r.status_code == 200 and r.json()["tenant_ids"] == [10, 20]
    assert client.get("/api/v1/keywords?tenant_id=10", headers=old).status_code == 401
    chosen2 = client.post("/api/v1/auth/select-tenant", headers=identity, json={"tenant_id": 10})
    assert chosen2.status_code == 200
    assert client.get("/api/v1/keywords?tenant_id=10", headers=headers(chosen2.json()["access_token"])).status_code == 200
    async def rows():
        async with factory() as s:
            return list((await s.scalars(select(Grant).order_by(Grant.id))).all()), (await s.get(User, 1)).tenant_id
    grants, default = run(rows())
    assert len(grants) == 3 and grants[0].revoked_by == 2
    assert grants[0].revoke_reason == "admin_uncheck" and grants[0].revoked_at is not None
    assert grants[-1].id != 101 and grants[-1].granted_by == 2 and default == 20


@pytest.mark.parametrize("ids,default", [([], 10), ([10, 99], 10), ([10], 20), ([True], 10),
    (["10"], 10), ([-1], 10), ([10.5], 10), ([2**63], 10), ([10], None)])
def test_invalid_lists_and_defaults_never_partially_write(db, ids, default):
    client, _, _ = db
    first = detail(client)
    assert save(client, ids, default, first["grants_version"]).status_code == 422
    assert detail(client)["grants_version"] == first["grants_version"]


def test_named_admin_only_non_advisor_rejection_and_legacy_field_bypass(db):
    client, _, _ = db
    for uid in (1, 3):
        credential = token(tid=10, gid=101) if uid == 1 else token(advisor=False, user_id=uid)
        r = client.patch("/api/v1/users/1", headers=headers(credential),
                         json={"tenant_ids": [10], "default_tenant_id": 10})
        assert r.status_code == 403
    from app.config import get_settings
    r = client.patch("/api/v1/users/1", headers={"X-API-Key": get_settings().admin_api_key},
                     json={"tenant_ids": [10], "default_tenant_id": 10})
    assert r.status_code == 403
    r = client.patch("/api/v1/users/3", headers=admin(), json={"tenant_ids": [10]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "TENANT_IDS_ONLY_FOR_ADVISOR"
    for payload in ({"tenant_id": 30}, {"tenant_id": None}, {"clear_tenant": True}):
        assert client.patch("/api/v1/users/1", headers=admin(), json=payload).status_code == 422
    r = client.patch("/api/v1/users/1", headers=admin(), json={
        "tenant_ids": [20], "expected_grants_version": detail(client)["grants_version"]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "ADVISOR_DEFAULT_TENANT_REQUIRED"


def test_create_deduplicates_and_returns_contract_without_expected_version(db):
    client, factory, _ = db
    r = client.post("/api/v1/users", headers=admin(), json={"username": "new-advisor", "password": "local-fixture-password",
        "role_id": 1, "tenant_ids": [20, 10, 20]})
    assert r.status_code == 200, r.text
    value = r.json()
    assert value["tenant_ids"] == [10, 20] and value["default_tenant_id"] == 20
    assert value["is_advisor"] and len(value["grants_version"]) == 16
    async def grants():
        async with factory() as s:
            return list((await s.scalars(select(Grant).where(Grant.user_id == value["id"]))).all())
    assert all(g.granted_by == 2 and g.grant_source == "admin" for g in run(grants()))
    for role, ids in ((1, []), (3, [10])):
        assert client.post("/api/v1/users", headers=admin(), json={"username": "invalid-new", "password": "local-fixture-password",
            "role_id": role, "tenant_ids": ids}).status_code == 422


def test_login_single_backfill_selection_ttl_and_two_tabs_do_not_change_default(db):
    client, factory, _ = db
    async def prepare():
        async with factory() as s:
            (await s.get(User, 1)).password_hash = hash_password("local-fixture-password")
            grant = await s.get(Grant, 102)
            grant.revoked_at = datetime.now(timezone.utc) + timedelta(seconds=1)
            grant.revoked_by = 2
            grant.revoke_reason = "admin_uncheck"
            await s.commit()
    run(prepare())
    login = client.post("/api/v1/auth/login", json={"username": "advisor", "password": "local-fixture-password"})
    assert login.status_code == 200 and login.json()["user"]["is_advisor"] is True
    identity = login.json()["token"]
    claims = jwt.decode(identity, _jwt_secret(), algorithms=[JWT_ALG], audience="advisor-session")
    chosen = client.post("/api/v1/auth/select-tenant", headers=headers(identity), json={"tenant_id": 10})
    assert chosen.status_code == 200
    value = chosen.json()
    assert value["tenant_name"] == "A" and value["token_type"] == "bearer"
    business = jwt.decode(value["access_token"], _jwt_secret(), algorithms=[JWT_ALG], audience="advisor-business")
    assert business["sub"] == "1" and business["gid"] == 101 and business["tid"] == 10
    assert business["exp"] <= business["auth_exp"] == claims["exp"]
    assert datetime.fromisoformat(value["expires_at"]).timestamp() == business["exp"]
    again = client.post("/api/v1/auth/select-tenant", headers=headers(value["access_token"]), json={"tenant_id": 10})
    new_claims = jwt.decode(again.json()["access_token"], _jwt_secret(), algorithms=[JWT_ALG], audience="advisor-business")
    assert new_claims["auth_exp"] == claims["exp"]
    assert detail(client)["default_tenant_id"] == 10
    assert client.get("/api/v1/keywords?tenant_id=10", headers=headers(value["access_token"])).status_code == 200


def test_selection_ungranted_empty_module_disabled_and_rate_limit(db):
    client, factory, _ = db
    h = headers(token())
    r = client.post("/api/v1/auth/select-tenant", headers=h, json={"tenant_id": 30})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "ADVISOR_TENANT_NOT_GRANTED"
    assert client.post("/api/v1/auth/select-tenant", headers=h, json={"tenant_id": True}).status_code == 422
    assert client.post("/api/v1/auth/select-tenant", headers=h, json={"tenant_id": 10, "target_user_id": 2}).status_code == 422
    async def disable():
        async with factory() as s:
            module = await s.scalar(select(TenantModule).where(TenantModule.tenant_id == 20))
            module.status = "disabled"
            await s.commit()
    run(disable())
    r = client.post("/api/v1/auth/select-tenant", headers=h, json={"tenant_id": 20})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "ADVISOR_TENANT_MODULE_UNAVAILABLE"
    assert save(client, [10, 20], 10, detail(client)["grants_version"]).status_code == 422
    for _ in range(8):
        assert client.post("/api/v1/auth/select-tenant", headers=h, json={"tenant_id": 10}).status_code == 200
    assert client.post("/api/v1/auth/select-tenant", headers=h, json={"tenant_id": 10}).status_code == 429


def test_disabled_switch_does_not_disable_guard(db):
    client, _, settings = db
    settings.advisor_multi_tenant_enabled = False
    r = client.post("/api/v1/auth/select-tenant", headers=headers(token()), json={"tenant_id": 10})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "ADVISOR_MULTI_TENANT_DISABLED"
    assert save(client, [10], 10, detail(client)["grants_version"]).status_code == 422
    assert client.get("/api/v1/keywords?tenant_id=30", headers=headers(token(tid=10, gid=101))).status_code == 403


def test_audit_failure_rolls_back_grants_and_default(db, monkeypatch):
    client, _, _ = db
    first = detail(client)
    async def fail(session, *args):
        await session.rollback()
        raise HTTPException(503, "synthetic audit unavailable")
    monkeypatch.setattr(users, "audit_business", fail)
    assert save(client, [20], 20, first["grants_version"]).status_code == 503
    assert detail(client)["grants_version"] == first["grants_version"]


def test_missing_table_create_rolls_back_and_non_advisor_patch_still_works(db):
    client, factory, _ = db
    async def drop():
        async with factory() as s:
            await s.execute(text("DROP TABLE advisor_tenant_grants"))
            await s.commit()
    run(drop())
    r = client.post("/api/v1/users", headers=admin(), json={"username": "cannot-persist", "password": "local-fixture-password",
        "role_id": 1, "tenant_ids": [10]})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "ADVISOR_GRANTS_UNAVAILABLE"
    async def count():
        async with factory() as s:
            return await s.scalar(select(User).where(User.username == "cannot-persist"))
    assert run(count()) is None
    assert client.patch("/api/v1/users/3", headers=admin(), json={"display_name": "正常客户"}).status_code == 200
