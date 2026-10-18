"""Pure fake-session checks: no DB, no configuration and no credentials."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.security.advisor_management import lock_named_admin
from app.security.auth import AuthContext, require_admin, require_auth
from app.api import roles, users
from app.database import get_session


class FakeSession:
    def __init__(self, permissions):
        self.role = SimpleNamespace(name='账户维护', is_system=False, permissions=permissions)
        self.actor = SimpleNamespace(id=7, role_id=3, is_active=True, locked_until=None, tenant_id=None)

    async def scalars(self, statement):
        return SimpleNamespace(all=lambda: [self.actor])

    async def get(self, model, ident, **kwargs):
        return self.role


@pytest.mark.parametrize('permissions', [
    {}, {'settings.accounts': 'edit'}, {'settings.customers': 'edit'},
    {'settings.accounts': 'edit', 'settings.customers': 'view'},
    {'settings.accounts': 'view', 'settings.customers': 'edit'},
    {'seo.site': 'edit', 'seo.content': 'edit'},
])
def test_partial_permissions_cannot_change_advisor_grants(permissions):
    session = FakeSession(permissions)
    with pytest.raises(HTTPException) as error:
        asyncio.run(lock_named_admin(session, SimpleNamespace(user_id=7)))
    assert error.value.status_code == 403
    assert error.value.detail['code'] == 'ADVISOR_NAMED_ADMIN_REQUIRED'


def test_complete_platform_administrator_can_manage_grants():
    session = FakeSession({'settings.accounts': 'edit', 'settings.customers': 'edit'})
    assert asyncio.run(lock_named_admin(session, SimpleNamespace(user_id=7))) is None


def test_builtin_administrator_retains_effective_platform_permissions():
    session = FakeSession({})
    session.role.name = '管理员'
    session.role.is_system = True
    assert asyncio.run(lock_named_admin(session, SimpleNamespace(user_id=7))) is None


@pytest.mark.parametrize('changes', [
    {'is_active': False}, {'tenant_id': 1},
    {'locked_until': datetime.now(timezone.utc) + timedelta(hours=1)},
])
def test_full_permissions_still_require_an_active_unbound_unlocked_actor(changes):
    session = FakeSession({'settings.accounts': 'edit', 'settings.customers': 'edit'})
    for key, value in changes.items():
        setattr(session.actor, key, value)
    with pytest.raises(HTTPException) as error:
        asyncio.run(lock_named_admin(session, SimpleNamespace(user_id=7)))
    assert error.value.status_code == 403


def test_unnamed_identity_is_rejected_before_session_access():
    with pytest.raises(HTTPException) as error:
        asyncio.run(lock_named_admin(None, SimpleNamespace(user_id=None)))
    assert error.value.status_code == 403


@pytest.mark.parametrize('permissions', [
    {}, {'settings.accounts': 'edit'}, {'settings.customers': 'edit'},
    {'settings.accounts': 'edit', 'settings.customers': 'view'},
    {'settings.accounts': 'view', 'settings.customers': 'edit'},
    {'seo.site': 'edit', 'seo.content': 'edit'},
])
def test_partial_role_cannot_reach_global_user_or_role_mutations(permissions):
    # Every user/role router depends on this gate. Otherwise an account-only
    # actor could first assign a stronger role and then pass the grant gate.
    ctx = AuthContext(7, 'account-maintenance-fixture', 'custom', None, permissions)
    with pytest.raises(HTTPException) as error:
        asyncio.run(require_admin(ctx))
    assert error.value.status_code == 403


def test_full_global_admin_gate_accepts_complete_permissions():
    ctx = AuthContext(7, 'platform-admin-fixture', 'custom', None,
        {'settings.accounts': 'edit', 'settings.customers': 'edit'})
    assert asyncio.run(require_admin(ctx)) is ctx


def test_operational_superadmin_context_semantics_are_unchanged():
    # No key is created or used; named grant writes still reject user_id=None.
    ctx = AuthContext(None, 'test-context', 'superadmin', None, is_superadmin=True)
    assert asyncio.run(require_admin(ctx)) is ctx


def test_bound_account_still_cannot_manage_global_users_or_roles():
    ctx = AuthContext(7, 'bound-fixture', 'custom', 1,
        {'settings.accounts': 'edit', 'settings.customers': 'edit'})
    with pytest.raises(HTTPException) as error:
        asyncio.run(require_admin(ctx))
    assert error.value.status_code == 403


@pytest.mark.parametrize('method,path,payload', [
    ('GET', '/api/v1/users', None),
    ('POST', '/api/v1/roles', {'name': 'synthetic-role', 'permissions': {}}),
])
def test_account_only_actor_cannot_enter_real_management_routers(method, path, payload):
    app = FastAPI()
    app.include_router(users.router)
    app.include_router(roles.router)
    ctx = AuthContext(7, 'account-maintenance-fixture', 'custom', None, {'settings.accounts': 'edit'})
    app.dependency_overrides[require_auth] = lambda: ctx
    async def forbidden_session():
        raise AssertionError('Partial administrator must be rejected before database access')
        yield
    app.dependency_overrides[get_session] = forbidden_session
    with TestClient(app) as client:
        response = client.request(method, path, json=payload)
    assert response.status_code == 403
