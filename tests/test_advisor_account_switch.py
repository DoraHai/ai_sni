"""Offline authorization checks; no database or migration is run."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.exc import DBAPIError
from starlette.requests import Request

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "0123456789abcdef")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.api.auth import (AccountLinkRequest, SwitchAccountRequest, link_advisor_accounts,
                          linked_accounts, router, switch_account, unlink_advisor_account, _audit_ip)
from app.models.advisor_account import AdvisorAccountLink, AdvisorAccountSwitchAudit
from app.models.role import Role
from app.models.tenant import Tenant
from app.models.user import User
from app.security.auth import AuthContext
from app.security.auth import issue_token, require_auth


def actor(user_id=1):
    return AuthContext(user_id, "advisor", "advisor", 10 if user_id else None,
                       {"seo.site": "edit", "seo.content": "edit"})


def request(token=None):
    if token is None:
        token = issue_token(User(id=1, username="source", role_id=1, tenant_id=10,
                                 is_active=True, password_hash="unused"))
    return Request({"type": "http", "method": "POST", "path": "/api/v1/auth/switch-account",
                    "headers": [(b"authorization", f"Bearer {token}".encode())],
                    "client": ("127.0.0.1", 40000)})


def test_audit_ip_uses_nginx_real_ip_only_from_local_proxy():
    proxied = Request({"type": "http", "method": "POST", "path": "/", "client": ("127.0.0.1", 40000),
                       "headers": [(b"x-real-ip", b"203.0.113.7")]})
    remote = Request({"type": "http", "method": "POST", "path": "/", "client": ("192.0.2.4", 40000),
                      "headers": [(b"x-real-ip", b"203.0.113.7")]})
    assert _audit_ip(proxied) == "203.0.113.7"
    assert _audit_ip(remote) == "192.0.2.4"


def fixture(*, linked=True, active=True, tenant=20, admin=False, locked=False):
    group = uuid4()
    users = {
        1: User(id=1, username="source", display_name="Source", role_id=1,
                tenant_id=10, is_active=True, password_hash="unused"),
        2: User(id=2, username="target", display_name="Target", role_id=2 if admin else 1,
                tenant_id=tenant, is_active=active, password_hash="unused"),
        99: User(id=99, username="admin", display_name="Admin", role_id=2,
                 tenant_id=None, is_active=True, password_hash="unused"),
    }
    roles = {
        1: Role(id=1, name="advisor", is_system=False,
                permissions={"seo.site": "edit", "seo.content": "edit"}),
        2: Role(id=2, name="admin", is_system=False,
                permissions={"seo.site": "edit", "seo.content": "edit", "settings.accounts": "edit"}),
    }
    if locked:
        users[2].locked_until = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5)
    if admin:
        roles[2].name = "管理员"
        roles[2].is_system = True
    session = AsyncMock()
    session.add = MagicMock()

    async def get(model, ident, **kwargs):
        if model is User:
            return users.get(ident)
        if model is Role:
            return roles.get(ident)
        if model is AdvisorAccountLink:
            return SimpleNamespace(user_id=ident, group_id=group if ident == 1 or linked else uuid4(),
                                   tenant_id=users[ident].tenant_id)
        if model is Tenant:
            return SimpleNamespace(id=ident, name="Customer B")
        return None

    session.get.side_effect = get
    session.scalar.return_value = 0
    session.link_group = group
    return session, users


def test_account_switch_routes_are_registered():
    methods = {route.path: route.methods for route in router.routes}
    assert "POST" in methods["/api/v1/auth/switch-account"]
    assert "GET" in methods["/api/v1/auth/linked-accounts"]
    assert "POST" in methods["/api/v1/auth/account-links"]
    assert "DELETE" in methods["/api/v1/auth/account-links/{user_id}"]


@pytest.mark.parametrize("case,status", [
    ("same_group", 200), ("other_group", 403), ("disabled", 403),
    ("null_tenant", 403), ("same_tenant", 403), ("admin", 403),
    ("locked", 403), ("anonymous", 403),
])
def test_switch_account_authorization_and_durable_audit(case, status):
    session, users = fixture(linked=case != "other_group", active=case != "disabled",
                             tenant=None if case == "null_tenant" else 10 if case == "same_tenant" else 20,
                             admin=case == "admin",
                             locked=case == "locked")
    source_link = SimpleNamespace(user_id=1, group_id=session.link_group, tenant_id=10)
    target_link = SimpleNamespace(user_id=2, group_id=session.link_group if case != "other_group" else uuid4(),
                                  tenant_id=users[2].tenant_id)
    session.scalar.side_effect = [source_link, 0, target_link]
    ctx = actor(None if case == "anonymous" else 1)
    with patch("app.api.auth.issue_token", return_value="target-jwt"):
        if status == 200:
            result = asyncio.run(switch_account(SwitchAccountRequest(target_user_id=2), request(), ctx, session))
            assert result["token"] == "target-jwt"
            assert result["user"]["tenant_id"] == 20
            assert users[2].last_login_at is None
            audit = session.add.call_args.args[0]
            assert isinstance(audit, AdvisorAccountSwitchAudit)
            assert (audit.from_user_id, audit.to_user_id, audit.status, audit.ip_address) == (1, 2, "success", "127.0.0.1")
            session.commit.assert_awaited_once()
        else:
            with pytest.raises(HTTPException) as denied:
                asyncio.run(switch_account(SwitchAccountRequest(target_user_id=2), request(), ctx, session))
            assert denied.value.status_code == status
            if case != "anonymous":
                audit = session.add.call_args.args[0]
                assert isinstance(audit, AdvisorAccountSwitchAudit)
                assert audit.status == "denied"
                session.commit.assert_awaited_once()
            else:
                session.commit.assert_not_awaited()


def test_linked_accounts_only_returns_current_group_active_advisor():
    session, _ = fixture()
    session.scalars.return_value = [User(id=2, username="target", display_name="Target",
                                         role_id=1, tenant_id=20, is_active=True, password_hash="unused")]
    result = asyncio.run(linked_accounts(actor(), session))
    assert result == {"accounts": [{"id": 2, "display_name": "Target", "customer_name": "Customer B"}]}


def test_only_named_admin_can_create_and_remove_distinct_tenant_links():
    session, users = fixture()
    original_get = session.get.side_effect

    async def get(model, ident, **kwargs):
        if model is AdvisorAccountLink:
            return None
        return await original_get(model, ident, **kwargs)

    session.get.side_effect = get
    session.scalars.return_value = []
    admin = AuthContext(99, "admin", "admin", None, {"settings.accounts": "edit"})
    with patch("app.security.platform_admin.acquire_platform_admin_lock", new=AsyncMock()):
        with pytest.raises(HTTPException) as denied:
            asyncio.run(link_advisor_accounts(AccountLinkRequest(user_ids=[1, 2]),
                                              AuthContext(None, "key", "key", None, {}, True), session))
        assert denied.value.status_code == 403
        result = asyncio.run(link_advisor_accounts(AccountLinkRequest(user_ids=[1, 2]), admin, session))
        assert result["user_ids"] == [1, 2]
        assert len([c for c in session.add.call_args_list if isinstance(c.args[0], AdvisorAccountLink)]) == 2
        users[2].tenant_id = 10
        with pytest.raises(HTTPException) as duplicate_tenant:
            asyncio.run(link_advisor_accounts(AccountLinkRequest(user_ids=[1, 2]), admin, session))
        assert duplicate_tenant.value.status_code == 403


def test_admin_unlink_revokes_membership():
    session, _ = fixture()
    session.scalars.return_value = []
    admin = AuthContext(99, "admin", "admin", None, {"settings.accounts": "edit"})
    with patch("app.security.platform_admin.acquire_platform_admin_lock", new=AsyncMock()):
        assert asyncio.run(unlink_advisor_account(2, admin, session)) == {"status": "ok"}
    session.delete.assert_awaited_once()
    session.commit.assert_awaited_once()
    audit = session.add.call_args.args[0]
    assert isinstance(audit, AdvisorAccountSwitchAudit)
    assert audit.action == "unlink" and audit.actor_user_id == 99 and audit.group_id


def test_switch_is_limited_by_recent_audit_records():
    session, _ = fixture()
    session.scalar.side_effect = [SimpleNamespace(user_id=1, group_id=session.link_group, tenant_id=10), 10]
    with pytest.raises(HTTPException) as denied:
        asyncio.run(switch_account(SwitchAccountRequest(target_user_id=2), request(), actor(), session))
    assert denied.value.status_code == 429
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


def test_unlinked_source_and_target_do_not_write_audit_or_take_global_lock():
    session, _ = fixture()
    original = session.get.side_effect
    async def no_source_link(model, ident, **kwargs):
        if model is AdvisorAccountLink and ident == 1:
            return None
        return await original(model, ident, **kwargs)
    session.get.side_effect = no_source_link
    with patch("app.security.platform_admin.acquire_platform_admin_lock", new=AsyncMock()) as global_lock:
        with pytest.raises(HTTPException) as denied:
            asyncio.run(switch_account(SwitchAccountRequest(target_user_id=2), request(), actor(), session))
    assert denied.value.status_code == 403
    global_lock.assert_not_awaited()
    session.add.assert_not_called()

    session, _ = fixture()
    session.scalar.side_effect = [SimpleNamespace(user_id=1, group_id=session.link_group, tenant_id=10), 0, None]
    with pytest.raises(HTTPException) as denied:
        asyncio.run(switch_account(SwitchAccountRequest(target_user_id=2), request(), actor(), session))
    assert denied.value.status_code == 403
    assert session.add.call_args.args[0].reason == "not_linked"


def test_ineligible_source_is_rejected_before_link_query_and_write():
    session, users = fixture()
    users[1].is_active = False
    with pytest.raises(HTTPException) as denied:
        asyncio.run(switch_account(SwitchAccountRequest(target_user_id=2), request(), actor(), session))
    assert denied.value.status_code == 403
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


def test_target_tenant_snapshot_mismatch_is_denied():
    session, users = fixture()
    session.scalar.side_effect = [SimpleNamespace(user_id=1, group_id=session.link_group, tenant_id=10),
                                  0, SimpleNamespace(user_id=2, group_id=session.link_group, tenant_id=20)]
    users[2].tenant_id = 30
    with pytest.raises(HTTPException) as denied:
        asyncio.run(switch_account(SwitchAccountRequest(target_user_id=2), request(), actor(), session))
    assert denied.value.status_code == 403
    assert session.add.call_args.args[0].reason == "target_ineligible"


def test_missing_link_schema_is_service_unavailable():
    session, _ = fixture()
    original = session.get.side_effect
    async def missing(model, ident, **kwargs):
        if model is AdvisorAccountLink:
            raise DBAPIError("SELECT", {}, SimpleNamespace(sqlstate="42P01"))
        return await original(model, ident, **kwargs)
    session.get.side_effect = missing
    for operation in (lambda: linked_accounts(actor(), session),
                      lambda: switch_account(SwitchAccountRequest(target_user_id=2), request(), actor(), session)):
        with pytest.raises(HTTPException) as denied:
            asyncio.run(operation())
        assert denied.value.status_code == 503


def test_switch_token_expires_in_two_hours_and_unlink_revokes_it():
    session, users = fixture()
    auth_exp = int((datetime.now(timezone.utc) + timedelta(hours=3)).timestamp())
    token = issue_token(users[2], switch_source_id=1, switch_group_id=str(session.link_group),
                        root_source_id=1, auth_exp=auth_exp)
    import jwt
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["via"] == "advisor_switch"
    assert claims["src"] == 1 and claims["grp"] == str(session.link_group)
    assert claims["root_src"] == 1 and claims["auth_exp"] == auth_exp
    assert 0 < claims["exp"] - datetime.now(timezone.utc).timestamp() <= 7200
    bearer = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    assert asyncio.run(require_auth(bearer, None, None, session)).user_id == 2
    users[1].is_active = False
    with pytest.raises(HTTPException) as disabled_source:
        asyncio.run(require_auth(bearer, None, None, session))
    assert disabled_source.value.status_code == 401
    users[1].is_active = True
    original = session.get.side_effect
    async def old_snapshot(model, ident, **kwargs):
        if model is AdvisorAccountLink and ident == 2:
            return SimpleNamespace(user_id=2, group_id=session.link_group, tenant_id=20)
        return await original(model, ident, **kwargs)
    session.get.side_effect = old_snapshot
    users[2].tenant_id = 30
    with pytest.raises(HTTPException) as moved_target:
        asyncio.run(require_auth(bearer, None, None, session))
    assert moved_target.value.status_code == 401
    users[2].tenant_id = 20
    session.get.side_effect = original
    async def unlinked(model, ident, **kwargs):
        if model is AdvisorAccountLink and ident == 1:
            return None
        return await original(model, ident, **kwargs)
    session.get.side_effect = unlinked
    with pytest.raises(HTTPException) as denied:
        asyncio.run(require_auth(bearer, None, None, session))
    assert denied.value.status_code == 401


def test_chained_switch_keeps_original_expiry_and_root_revocation():
    session, users = fixture()
    users[3] = User(id=3, username="third", role_id=1, tenant_id=30,
                    is_active=True, password_hash="unused")
    original_get = session.get.side_effect
    async def get(model, ident, **kwargs):
        if model is AdvisorAccountLink and ident == 3:
            return SimpleNamespace(user_id=3, group_id=session.link_group, tenant_id=30)
        return await original_get(model, ident, **kwargs)
    session.get.side_effect = get
    session.scalar.side_effect = [SimpleNamespace(user_id=2, group_id=session.link_group, tenant_id=20),
                                  0, SimpleNamespace(user_id=3, group_id=session.link_group, tenant_id=30)]
    auth_exp = int((datetime.now(timezone.utc) + timedelta(seconds=90)).timestamp())
    first = issue_token(users[2], switch_source_id=1, switch_group_id=str(session.link_group),
                        root_source_id=1, auth_exp=auth_exp)
    ctx = AuthContext(2, "target", "advisor", 20, {"seo.site": "edit", "seo.content": "edit"})
    result = asyncio.run(switch_account(SwitchAccountRequest(target_user_id=3), request(first), ctx, session))
    import jwt
    claims = jwt.decode(result["token"], options={"verify_signature": False})
    assert claims["root_src"] == 1 and claims["src"] == 2
    assert claims["auth_exp"] == auth_exp and claims["exp"] <= auth_exp
    bearer = HTTPAuthorizationCredentials(scheme="Bearer", credentials=result["token"])
    assert asyncio.run(require_auth(bearer, None, None, session)).user_id == 3
    users[1].is_active = False
    with pytest.raises(HTTPException) as denied:
        asyncio.run(require_auth(bearer, None, None, session))
    assert denied.value.status_code == 401


def test_admin_link_routes_return_503_without_tables():
    session, _ = fixture()
    original_get = session.get.side_effect
    async def missing(model, ident, **kwargs):
        if model is AdvisorAccountLink:
            raise DBAPIError("SELECT", {}, SimpleNamespace(sqlstate="42P01"))
        return await original_get(model, ident, **kwargs)
    session.get.side_effect = missing
    admin = AuthContext(99, "admin", "admin", None, {"settings.accounts": "edit"})
    with patch("app.security.platform_admin.acquire_platform_admin_lock", new=AsyncMock()):
        for operation in (lambda: link_advisor_accounts(AccountLinkRequest(user_ids=[1, 2]), admin, session),
                          lambda: unlink_advisor_account(2, admin, session)):
            with pytest.raises(HTTPException) as denied:
                asyncio.run(operation())
            assert denied.value.status_code == 503


def test_link_audit_records_actor_group_and_reason():
    session, _ = fixture()
    original = session.get.side_effect
    async def no_link(model, ident, **kwargs):
        return None if model is AdvisorAccountLink else await original(model, ident, **kwargs)
    session.get.side_effect = no_link
    session.scalars.return_value = []
    admin = AuthContext(99, "admin", "admin", None, {"settings.accounts": "edit"})
    with patch("app.security.platform_admin.acquire_platform_admin_lock", new=AsyncMock()):
        asyncio.run(link_advisor_accounts(AccountLinkRequest(user_ids=[1, 2]), admin, session, request()))
    audits = [call.args[0] for call in session.add.call_args_list
              if isinstance(call.args[0], AdvisorAccountSwitchAudit)]
    assert len(audits) == 2
    assert all(a.action == "link" and a.actor_user_id == 99 and a.group_id and a.reason == "create" for a in audits)
