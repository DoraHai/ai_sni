"""Advisor GETs must not call providers or change customer profile caches."""
import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.ai import customer_profile as profile
from app.api import customer_profile as endpoint
from app.database import get_session
from app.security import advisor_request
from app.security.advisor_scope import AdvisorScope, is_advisor
from app.security.auth import AuthContext, require_scoped_auth


def context(advisor=True):
    permissions = {'monitor.profile': 'view'}
    if advisor:
        permissions.update({'seo.site': 'edit', 'seo.content': 'edit'})
    return AuthContext(user_id=7, username='advisor-fixture', role_name='fixture', tenant_id=1,
        permissions=permissions,
        advisor_scope=AdvisorScope(frozenset({1}), 1, 11) if advisor else None)


@pytest.fixture
def fixture(monkeypatch):
    tenant = SimpleNamespace(id=1, profile_summary=None, profile_generated_at=None)
    session = SimpleNamespace(get=AsyncMock(return_value=tenant), commit=AsyncMock())
    chat = AsyncMock(return_value={'summary': 'new provider summary'})
    monkeypatch.setattr(profile, 'chat_json', chat)
    monkeypatch.setattr(profile, 'is_enabled', lambda: True)
    monkeypatch.setattr(profile, 'profile_brief', lambda data: 'synthetic profile')
    monkeypatch.setattr(endpoint, 'ai_enabled', lambda: True)
    monkeypatch.setattr(endpoint, 'gather_profile', AsyncMock(return_value={'tenant_id': 1}))
    monkeypatch.setattr(advisor_request, 'ensure_module_access', AsyncMock())
    return tenant, session, chat


@pytest.mark.parametrize('cached', [None, 'cached profile'])
@pytest.mark.parametrize('force', [False, True])
def test_actual_advisor_get_is_read_only_even_on_cache_miss_or_refresh(fixture, cached, force):
    tenant, session, chat = fixture
    tenant.profile_summary = cached
    tenant.profile_generated_at = datetime(2026, 10, 18) if cached else None
    ctx = context()
    assert is_advisor(SimpleNamespace(name='advisor fixture', is_system=False, permissions=ctx.permissions))
    request = Request({'type': 'http', 'method': 'GET', 'scheme': 'https',
        'server': ('testserver', 443), 'path': '/api/v1/customer-profile',
        'query_string': b'tenant_id=1&refresh_summary=true', 'headers': []})
    # Exercise the real allowlist and its view-only RBAC before the HTTP handler.
    asyncio.run(advisor_request.guard_advisor_request(session, ctx, request, {'scope_kind': 'advisor_tenant'}))
    app = FastAPI()
    app.include_router(endpoint.router)
    app.dependency_overrides[require_scoped_auth] = lambda: ctx
    async def fake_session():
        yield session
    app.dependency_overrides[get_session] = fake_session
    with TestClient(app) as client:
        response = client.get('/api/v1/customer-profile', params={'tenant_id': 1, 'refresh_summary': str(force).lower()})
    assert response.status_code == 200
    assert response.json()['summary'] == cached
    assert tenant.profile_summary == cached
    chat.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.parametrize('cached', [None, 'cached profile'])
@pytest.mark.parametrize('force', [False, True])
def test_helper_read_only_never_calls_provider_or_commits(fixture, cached, force):
    tenant, session, chat = fixture
    tenant.profile_summary = cached
    result = asyncio.run(profile.generate_summary(session, tenant, {}, force=force, read_only=True))
    assert result == cached
    chat.assert_not_awaited()
    session.commit.assert_not_awaited()


def test_non_advisor_force_refresh_preserves_existing_behavior(fixture):
    tenant, session, chat = fixture
    tenant.profile_summary = 'cached profile'
    result = asyncio.run(profile.generate_summary(session, tenant, {}, force=True))
    assert result == tenant.profile_summary == 'new provider summary'
    chat.assert_awaited_once()
    session.commit.assert_awaited_once()


def test_profile_handler_rejects_a_different_customer_before_reading(fixture):
    tenant, session, chat = fixture
    app = FastAPI()
    app.include_router(endpoint.router)
    app.dependency_overrides[require_scoped_auth] = lambda: context()
    async def fake_session():
        yield session
    app.dependency_overrides[get_session] = fake_session
    with TestClient(app) as client:
        response = client.get('/api/v1/customer-profile?tenant_id=2')
    assert response.status_code == 403
    assert response.json()['detail']['code'] == 'ADVISOR_TENANT_NOT_GRANTED'
    session.get.assert_not_awaited()
    chat.assert_not_awaited()
    session.commit.assert_not_awaited()


def test_non_advisor_http_refresh_keeps_the_writable_path(fixture):
    tenant, session, chat = fixture
    app = FastAPI()
    app.include_router(endpoint.router)
    app.dependency_overrides[require_scoped_auth] = lambda: context(advisor=False)
    async def fake_session():
        yield session
    app.dependency_overrides[get_session] = fake_session
    with TestClient(app) as client:
        response = client.get('/api/v1/customer-profile?tenant_id=1&refresh_summary=true')
    assert response.status_code == 200
    assert response.json()['summary'] == 'new provider summary'
    chat.assert_awaited_once()
    session.commit.assert_awaited_once()
