"""Pure fake-session checks: no DB, no configuration and no credentials."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.security.advisor_management import lock_named_admin


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
