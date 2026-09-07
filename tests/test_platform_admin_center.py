from __future__ import annotations

import asyncio
import os
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "1234567890abcdefsecret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.api.customer_modules import ModuleUpdate, require_customer_admin
from app.api.roles import UpdateRoleRequest, update_role
from app.api.users import (
    ResetPasswordRequest,
    UpdateUserRequest,
    _payload as user_payload,
    reset_user_password,
    update_user,
)
from app.models import Role, User
from app.permissions import effective_role_permissions, has_full_platform_admin
from app.security.auth import AuthContext, _build_context, require_admin


ROOT = Path(__file__).resolve().parents[1]


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _Session:
    def __init__(self, *, roles=(), users=(), user_query_rows=None):
        self.roles = list(roles)
        self.users = list(users)
        self.user_query_rows = user_query_rows
        self.commits = 0

    async def get(self, model, object_id):
        rows = self.roles if model is Role else self.users
        return next((row for row in rows if row.id == object_id), None)

    async def scalars(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is Role:
            return _Rows(self.roles)
        rows = self.users if self.user_query_rows is None else self.user_query_rows
        return _Rows(rows)

    async def scalar(self, _statement):
        return 0

    async def commit(self):
        self.commits += 1


def _role(role_id=1, *, name="管理员", is_system=True, permissions=None):
    return Role(
        id=role_id,
        name=name,
        is_system=is_system,
        permissions=permissions or {},
    )


def _user(user_id=1, *, role_id=1, tenant_id=None, active=True):
    return User(
        id=user_id,
        username=f"user-{user_id}",
        password_hash="stored-hash",
        role_id=role_id,
        tenant_id=tenant_id,
        is_active=active,
    )


def test_only_trusted_builtin_administrator_receives_dual_platform_invariant():
    trusted = effective_role_permissions("管理员", True, {})
    same_name_custom = effective_role_permissions("管理员", False, {})

    assert has_full_platform_admin(trusted)
    assert same_name_custom == {}


def test_runtime_context_repairs_trusted_admin_without_persisting_or_elevating_name_only():
    trusted_role = _role()
    trusted_user = _user()
    trusted = asyncio.run(_build_context(trusted_user, _Session(roles=[trusted_role])))
    assert has_full_platform_admin(trusted.permissions)
    assert trusted_role.permissions == {}

    custom_role = _role(2, is_system=False)
    custom_user = _user(2, role_id=2)
    custom = asyncio.run(_build_context(custom_user, _Session(roles=[custom_role])))
    assert custom.permissions == {}


def test_tenant_bound_identity_cannot_enter_global_customer_user_or_role_writes():
    ctx = AuthContext(
        7,
        "tenant-admin",
        "custom",
        4,
        {"settings.accounts": "edit", "settings.customers": "edit"},
    )
    with pytest.raises(HTTPException) as accounts:
        asyncio.run(require_admin(ctx))
    with pytest.raises(HTTPException) as customers:
        asyncio.run(require_customer_admin(ctx))
    assert accounts.value.status_code == customers.value.status_code == 403


def test_builtin_admin_role_cannot_drop_either_platform_permission():
    role = _role(permissions={"settings.accounts": "edit", "settings.customers": "edit"})
    actor = _user(role_id=role.id)
    session = _Session(roles=[role], users=[actor])
    ctx = AuthContext(actor.id, actor.username, role.name, None, role.permissions)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            update_role(
                role.id,
                UpdateRoleRequest(permissions={"settings.accounts": "edit"}),
                session,
                ctx,
            )
        )
    assert exc.value.status_code == 400
    assert session.commits == 0


def test_current_platform_admin_cannot_drop_customer_permission_from_own_role():
    role = _role(
        name="平台运维",
        is_system=False,
        permissions={"settings.accounts": "edit", "settings.customers": "edit"},
    )
    actor = _user(role_id=role.id)
    other_role = _role(
        2,
        name="备用管理员",
        is_system=False,
        permissions={"settings.accounts": "edit", "settings.customers": "edit"},
    )
    other = _user(2, role_id=other_role.id)
    ctx = AuthContext(actor.id, actor.username, role.name, None, role.permissions)

    with pytest.raises(HTTPException, match="当前账号失去平台管理能力"):
        asyncio.run(
            update_role(
                role.id,
                UpdateRoleRequest(permissions={"settings.accounts": "edit"}),
                _Session(roles=[role, other_role], users=[actor, other]),
                ctx,
            )
        )


def test_current_and_last_platform_admin_cannot_self_lock():
    role = _role(permissions={"settings.accounts": "edit", "settings.customers": "edit"})
    actor = _user(role_id=role.id)
    ctx = AuthContext(actor.id, actor.username, role.name, None, role.permissions)

    with pytest.raises(HTTPException, match="当前账号"):
        asyncio.run(update_user(actor.id, UpdateUserRequest(tenant_id=9), _Session(roles=[role], users=[actor]), ctx))

    other = _user(2, role_id=role.id)
    api_key = AuthContext(None, "api-key", "超级管理员", None, is_superadmin=True)
    with pytest.raises(HTTPException, match="最后一个平台管理员"):
        asyncio.run(
            update_user(
                other.id,
                UpdateUserRequest(is_active=False),
                _Session(roles=[role], users=[other], user_query_rows=[]),
                api_key,
            )
        )


def test_password_reset_is_separate_and_never_serializes_password_or_hash(monkeypatch):
    role = _role()
    user = _user()
    session = _Session(roles=[role], users=[user])
    monkeypatch.setattr("app.api.users.hash_password", lambda value: f"hashed:{value}")

    result = asyncio.run(
        reset_user_password(user.id, ResetPasswordRequest(new_password="new-password"), session)
    )
    payload = user_payload(user, {role.id: role.name}, {})

    assert result == {"status": "ok"}
    assert user.password_hash == "hashed:new-password"
    assert "password" not in payload and "password_hash" not in payload
    assert session.commits == 1


def test_module_contract_preserves_trial_and_expiry_without_checkbox_projection():
    request = ModuleUpdate(status="trial", expires_at=date(2026, 10, 7))
    assert request.model_dump() == {"status": "trial", "expires_at": date(2026, 10, 7)}

    customer_view = (ROOT / "frontend/src/views/settings/CustomerModulesView.vue").read_text(encoding="utf-8")
    assert "setCustomerModule(moduleContext.tenantId, moduleContext.code" in customer_view
    assert "status: moduleForm.status" in customer_view
    assert "expires_at: moduleForm.expires_at || null" in customer_view
    assert "checkbox-group" not in customer_view
    assert "不宣称多模块原子更新" in customer_view


def test_platform_shell_routes_permissions_and_legacy_redirects_are_explicit():
    router = (ROOT / "frontend/src/router/index.js").read_text(encoding="utf-8")
    app = (ROOT / "frontend/src/App.vue").read_text(encoding="utf-8")
    shell = (ROOT / "frontend/src/views/platform/PlatformAdminShell.vue").read_text(encoding="utf-8")

    for path in ("customers", "accounts", "roles"):
        assert f"path: '{path}'" in router
        assert f"/platform/{path}" in router + shell
    assert "path: '/settings/customers', redirect: '/platform/customers'" in router
    assert "path: '/settings/accounts', redirect: '/platform/accounts'" in router
    assert "path: '/settings/users', redirect: '/platform/accounts'" in router
    assert "path: '/admin/internal', redirect: '/platform/accounts'" in router
    assert "to.path.startsWith('/platform') && session.user?.tenant_id" in router
    assert "v-if=\"platformAdminPath\"" in app
    assert "⚙ 平台管理" in app
    assert "label: '系统设置'" not in app


def test_customer_status_and_connection_completeness_are_not_inferred():
    backend = (ROOT / "app/api/customer_modules.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend/src/views/settings/CustomerModulesView.vue").read_text(encoding="utf-8")
    assert '"state": "unavailable"' in backend
    assert '"reason": "not_recorded"' in backend
    assert '"completeness": "not_evaluated"' in backend
    assert "客户状态" in frontend and "未提供" in frontend
    assert "完整性未评估" in frontend
