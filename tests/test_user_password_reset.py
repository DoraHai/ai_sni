"""Exercise the deployed account-page contract without accessing any real accounts."""
from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from tests import sem_cockpit_fixtures  # configure isolated dummy settings
from app.api.users import router
from app.database import get_session
from app.models import User
from app.security.auth import AuthContext, require_auth, hash_password, verify_password


@pytest.fixture
def reset_client():
    app = FastAPI()
    app.include_router(router)
    user = User(id=7, username="synthetic", role_id=3, tenant_id=5,
                is_active=True, password_hash=hash_password("old-test-password"))
    session = AsyncMock()
    session.scalar.return_value = user
    ctx = AuthContext(1, "admin-test", "admin", None, {"settings.accounts": "edit"})
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_auth] = lambda: ctx
    with TestClient(app) as client:
        yield client, session, user, ctx, app


def test_reset_hashes_password_without_changing_account_or_echoing_secret(reset_client):
    client, session, user, _, _ = reset_client
    response = client.patch('/api/v1/users/7/password', json={'new_password': 'new-test-password'})
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}
    assert verify_password('new-test-password', user.password_hash)
    assert not verify_password('old-test-password', user.password_hash)
    assert (user.role_id, user.tenant_id, user.is_active) == (3, 5, True)
    assert 'FOR UPDATE' in str(session.scalar.call_args.args[0])
    session.commit.assert_awaited_once()


@pytest.mark.parametrize('password', [None, '', 'short', 'x' * 101])
def test_invalid_password_never_writes(reset_client, password):
    client, session, *_ = reset_client
    assert client.patch('/api/v1/users/7/password', json={'new_password': password}).status_code == 422
    session.scalar.assert_not_awaited()
    session.commit.assert_not_awaited()


def test_unknown_account_returns_404(reset_client):
    client, session, *_ = reset_client
    session.scalar.return_value = None
    response = client.patch('/api/v1/users/999/password', json={'new_password': 'new-test-password'})
    assert response.status_code == 404
    assert response.json()['detail'] == '用户不存在'
    session.commit.assert_not_awaited()


@pytest.mark.parametrize('tenant,permissions', [(5, {'settings.accounts':'edit'}), (None, {}), (None, {'settings.accounts':'view'})])
def test_unprivileged_reset_is_forbidden(reset_client, tenant, permissions):
    client, session, _, ctx, _ = reset_client
    ctx.tenant_id, ctx.permissions = tenant, permissions
    assert client.patch('/api/v1/users/7/password', json={'new_password': 'new-test-password'}).status_code == 403
    session.scalar.assert_not_awaited()
    session.commit.assert_not_awaited()


def test_unauthenticated_reset_does_not_write(reset_client):
    client, session, _, _, app = reset_client
    def unauthenticated():
        raise HTTPException(401, '未登录')
    app.dependency_overrides[require_auth] = unauthenticated
    assert client.patch('/api/v1/users/7/password', json={'new_password': 'new-test-password'}).status_code == 401
    session.commit.assert_not_awaited()


def test_user_list_exposes_existing_tenants_as_dropdown_options(reset_client):
    client, session, user, *_ = reset_client
    session.scalars.side_effect = [
        SimpleNamespace(all=lambda: [user]),
        SimpleNamespace(all=lambda: [SimpleNamespace(id=3, name="测试角色")]),
        SimpleNamespace(all=lambda: [SimpleNamespace(id=5, name="测试客户")]),
    ]

    response = client.get('/api/v1/users')

    assert response.status_code == 200
    assert response.json()['tenant_options'] == [{'id': 5, 'name': '测试客户'}]
    assert response.json()['users'][0]['tenant_name'] == '测试客户'
