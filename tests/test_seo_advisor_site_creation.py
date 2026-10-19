"""Site onboarding authorization with mocked sessions; no database connections."""
import asyncio
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request

from app.api.customer_modules import SeoSiteCreate, create_seo_site, seo_sites_router
from app.config import get_settings
from app.database import get_session
from app.models.module_workspace import SeoSite, TenantModule
from app.models.role import Role
from app.models.user import User
from app.security import advisor_tenant_auth as guard
from app.security.advisor_write_commit import recheck_advisor_before_commit
from app.security.advisor_write_objects import (
    check_write_objects, lock_manual_write_scope,
)
from app.security.advisor_write_routes import WRITE_ROUTES, check_write_fields, match_write_rule
from app.security.auth import AuthContext, require_auth
from app.security.seo_advisor_audit import install_commit_guard, operation_audit


RULE = WRITE_ROUTES['POST', '/api/v1/seo/sites']
BODY = dict(tenant_id=4, name='客户官网', domain='https://www.example.test/')


def actor(**updates):
    values = dict(user_id=7, username='fixture', role_name='顾问', tenant_id=4,
                  is_advisor=True, scope_kind='advisor_tenant', grant_id=10,
                  auth_exp=int(datetime.now(timezone.utc).timestamp()) + 3600,
                  advisor_tenant_ids=frozenset({4, 5}),
                  permissions={'seo.assets': 'edit', 'seo.site': 'edit', 'seo.content': 'edit'})
    values.update(updates)
    return AuthContext(**values)


def request(body=None, query='tenant_id=4', method='POST', path='/api/v1/seo/sites'):
    raw = json.dumps(BODY if body is None else body).encode()
    async def receive():
        return {'type': 'http.request', 'body': raw, 'more_body': False}
    route = next((route for route in seo_sites_router.routes
                  if route.path == path and method in route.methods), SimpleNamespace(path=path))
    return Request(dict(type='http', method=method, path=path, query_string=query.encode(),
                        headers=[(b'content-type', b'application/json')], path_params={},
                        route=route), receive)


def module(**updates):
    values = dict(id=44, tenant_id=4, module_code='seo', status='active', expires_at=None)
    values.update(updates)
    return SimpleNamespace(**values)


def session_for_create():
    pending = []
    session = SimpleNamespace(scalar=AsyncMock(return_value=module()),
                              add=pending.append, new=pending, dirty=[], deleted=[],
                              no_autoflush=nullcontext(), rollback=AsyncMock(), refresh=AsyncMock())
    async def commit():
        for row in pending:
            row.id, row.status = 101, 'active'
            row.created_at = datetime.now(timezone.utc)
    session.commit = AsyncMock(side_effect=commit)
    return session


@pytest.mark.parametrize('extra', [dict(site_id=2), dict(status='paused'),
                                    dict(advisor_user_id=7), dict(api_key='fixture')])
def test_site_creation_rejects_unapproved_fields(extra):
    with pytest.raises(HTTPException) as error:
        check_write_fields(RULE, BODY | extra)
    assert error.value.status_code == 403


def test_site_creation_route_match_is_exact():
    assert match_write_rule(request()) is RULE
    assert match_write_rule(request(path='/api/v1/seo/sites/extra')) is None
    assert match_write_rule(request(method='PUT')) is None


def test_legacy_scope_rule_without_route_metadata_preserves_scope_rejection():
    # Existing object helpers also accept minimal assignment-only rule objects.
    # They must keep checking tenant scope instead of failing on new metadata.
    ctx = actor(advisor_tenant_ids=frozenset({5}))
    session = session_for_create()
    with pytest.raises(HTTPException) as error:
        asyncio.run(check_write_objects(session, ctx, request(), BODY,
                                        SimpleNamespace(assignment='site')))
    assert error.value.status_code == 403
    assert error.value.detail['code'] == 'ADVISOR_TENANT_NOT_GRANTED'
    session.scalar.assert_not_called()


@pytest.mark.parametrize('body,query,updates,status', [
    (BODY | {'tenant_id': 6}, 'tenant_id=4', {}, 403),  # ungranted
    (BODY | {'tenant_id': 5}, 'tenant_id=5', {}, 403),  # granted, unselected
    (BODY, 'tenant_id=5', {}, 403),
    (BODY, 'tenant_id=4&tenant_id=5', {}, 403),
    (BODY, 'tenant_id=4&site_id=88', {}, 403),  # cross-site scope injection
    ({'name': '官网', 'domain': 'example.test'}, 'tenant_id=4', {}, 403),
    (BODY, 'tenant_id=4', {'scope_kind': 'advisor_identity', 'grant_id': None}, 409),
    (BODY, 'tenant_id=4', {'advisor_tenant_ids': frozenset()}, 403),
])
def test_site_creation_rejects_wrong_or_missing_selected_scope(body, query, updates, status):
    session = session_for_create()
    with pytest.raises(HTTPException) as error:
        asyncio.run(check_write_objects(session, actor(**updates), request(body, query), body, RULE))
    assert error.value.status_code == status
    session.commit.assert_not_called()
    assert session.new == []


@pytest.mark.parametrize('mod', [None, module(status='suspended'), module(status='closed'),
                                 module(expires_at=date.today()-timedelta(days=1))])
def test_site_creation_locked_scope_keeps_entitlement_restrictions(mod):
    session = session_for_create()
    session.scalar.return_value = mod
    with pytest.raises(HTTPException) as error:
        asyncio.run(lock_manual_write_scope(session, actor(), request(), BODY, RULE))
    assert error.value.status_code == 403
    session.commit.assert_not_called()


def test_site_creation_admission_keeps_existing_switch_and_explicit_tenant(monkeypatch):
    settings = get_settings().model_copy(update={'advisor_scoped_content_writes_enabled': True})
    monkeypatch.setattr('app.config.get_settings', lambda: settings)
    async def run():
        ctx, session, req = actor(), session_for_create(), request()
        await guard.enforce_advisor_request(req, ctx, session)
        assert ctx.advisor_write_rule is RULE
        assert ctx.advisor_write_scope == (req, BODY, RULE)
        assert session._seo_advisor_commit_guard
        # Only tenant-module reads, no existing site assignment or new grant.
        assert session.new == []
        assert all('seo_site_advisor_assignments' not in str(call.args[0])
                   for call in session.scalar.await_args_list)
        for query in ['', 'tenant_id=4&site_id=88']:
            with pytest.raises(HTTPException) as error:
                await guard.enforce_advisor_request(request(query=query), actor(), session_for_create())
            assert error.value.status_code == 403
        settings.advisor_scoped_content_writes_enabled = False
        with pytest.raises(HTTPException) as error:
            await guard.enforce_advisor_request(request(), actor(), session_for_create())
        assert error.value.detail['code'] == 'ADVISOR_HIGH_RISK_WRITES_DISABLED'
    asyncio.run(run())


def test_site_creation_admission_rejects_nested_payload_before_reads(monkeypatch):
    settings = get_settings().model_copy(update={'advisor_scoped_content_writes_enabled': True})
    monkeypatch.setattr('app.config.get_settings', lambda: settings)
    session = session_for_create()
    with pytest.raises(HTTPException) as error:
        asyncio.run(guard.enforce_advisor_request(request(BODY | {'name': {'tenant_id': 5}}), actor(), session))
    assert error.value.status_code == 422
    session.scalar.assert_not_called()


@pytest.mark.parametrize('permissions', [{}, {'seo.assets': 'view', 'seo.site': 'edit'},
                                       {'seo.assets': 'edit', 'seo.site': 'view'}])
def test_site_creation_needs_existing_edit_permissions(monkeypatch, permissions):
    settings = get_settings().model_copy(update={'advisor_scoped_content_writes_enabled': True})
    monkeypatch.setattr('app.config.get_settings', lambda: settings)
    with pytest.raises(HTTPException) as error:
        asyncio.run(guard.enforce_advisor_request(request(), actor(permissions=permissions), session_for_create()))
    assert error.value.status_code == 403


def test_site_creation_success_records_actor_tenant_site_time_without_new_permissions(monkeypatch, caplog):
    from app.security import advisor_write_commit
    recheck = AsyncMock()
    monkeypatch.setattr(advisor_write_commit, 'recheck_advisor_before_commit', recheck)
    ctx, session, req = actor(), session_for_create(), request()
    req.state.seo_advisor_evidence = {'requested_object_ids': {'tenant_id': 4}}
    install_commit_guard(session, ctx, req)
    result = asyncio.run(create_seo_site(SeoSiteCreate(**BODY), ctx, session))
    assert (result['id'], result['tenant_id'], result['canonical_domain']) == (101, 4, 'example.test')
    assert len(session.new) == 1 and isinstance(session.new[0], SeoSite)
    session.refresh.assert_not_called()  # no assignment means filtered readback is unavailable
    recheck.assert_awaited_once_with(session, ctx)
    event = next(json.loads(row.message) for row in caplog.records
                 if 'seo_advisor_operation' in row.message)
    assert (event['user_id'], event['tenant_id'], event['result']) == (7, 4, 'committed')
    assert event['created_objects'] == [{'table': 'seo_sites', 'id': 101}]
    assert event['time']


@pytest.mark.parametrize('revoked,role_changed,expired', [(False, False, False), (True, False, False),
                                                        (False, True, False), (False, False, True)])
def test_site_creation_commit_rechecks_grant_role_and_module(revoked, role_changed, expired):
    ctx, req = actor(), request()
    ctx.advisor_write_rule, ctx.advisor_write_scope = RULE, (req, BODY, RULE)
    role = SimpleNamespace(name='顾问', is_system=True, permissions=ctx.permissions)
    if role_changed:
        role.permissions = {}
    session = session_for_create()
    session.scalar.side_effect = [SimpleNamespace(id=7, is_active=True, locked_until=None,
                                                  role_id=1, tenant_id=4), role,
                                 module(expires_at=date.today()-timedelta(days=1)) if expired else module()]
    session.scalars = AsyncMock(return_value=[SimpleNamespace(id=10, tenant_id=4,
                                  revoked_at=datetime.now(timezone.utc) if revoked else None)])
    if revoked or role_changed or expired:
        with pytest.raises(HTTPException):
            asyncio.run(recheck_advisor_before_commit(session, ctx))
        session.rollback.assert_awaited_once()
    else:
        asyncio.run(recheck_advisor_before_commit(session, ctx))
        module_query = session.scalar.await_args_list[-1].args[0]
        assert module_query._for_update_arg is not None
        session.rollback.assert_not_called()


@pytest.mark.parametrize('superadmin', [False, True])
def test_site_creation_customer_and_superadmin_still_refresh(superadmin):
    ctx = actor(is_advisor=False, is_superadmin=superadmin,
                tenant_id=None if superadmin else 4)
    session = session_for_create()
    assert asyncio.run(create_seo_site(SeoSiteCreate(**BODY), ctx, session))['id'] == 101
    session.refresh.assert_awaited_once()


def test_site_creation_duplicate_domain_keeps_409_and_rollback():
    session = session_for_create()
    session.commit.side_effect = IntegrityError('fixture', {}, Exception('unique constraint'))
    with pytest.raises(HTTPException) as error:
        asyncio.run(create_seo_site(SeoSiteCreate(**BODY), actor(), session))
    assert error.value.status_code == 409
    session.rollback.assert_awaited_once()


def test_site_creation_still_rejects_bad_domains():
    session = session_for_create()
    with pytest.raises(HTTPException) as error:
        asyncio.run(create_seo_site(SeoSiteCreate(**(BODY | {'domain': 'invalid'})), actor(), session))
    assert error.value.status_code == 400
    session.commit.assert_not_called()


@pytest.mark.parametrize('target,status', [(4, 200), (5, 403), (6, 403)])
def test_site_creation_mounted_handler_and_commit_guard(monkeypatch, caplog, target, status):
    """Real router/dependencies/handler/audit, replacing only identity and SQL I/O."""
    settings = get_settings().model_copy(update={'advisor_scoped_content_writes_enabled': True})
    monkeypatch.setattr('app.config.get_settings', lambda: settings)
    ctx, session = actor(), session_for_create()
    async def scalar(statement):
        entity = statement.column_descriptions[0]['entity']
        if entity is User:
            return SimpleNamespace(id=7, is_active=True, locked_until=None, role_id=1, tenant_id=4)
        if entity is Role:
            return SimpleNamespace(name='顾问', is_system=True, permissions=ctx.permissions)
        assert entity is TenantModule
        return module()
    session.scalar.side_effect = scalar
    session.scalars = AsyncMock(return_value=[SimpleNamespace(id=10, tenant_id=4, revoked_at=None)])
    async def identity(request: Request):
        await guard.enforce_advisor_request(request, ctx, session)
        return ctx
    async def sql_session():
        yield session
    app = FastAPI()
    app.middleware('http')(operation_audit)
    app.include_router(seo_sites_router)
    app.dependency_overrides[require_auth] = identity
    app.dependency_overrides[get_session] = sql_session
    response = TestClient(app).post('/api/v1/seo/sites', params={'tenant_id': target},
                                    json=BODY | {'tenant_id': target})
    assert response.status_code == status
    if status == 200:
        assert response.json()['id'] == 101
        assert len(session.new) == 1 and isinstance(session.new[0], SeoSite)
        events = [json.loads(row.message) for row in caplog.records if 'seo_advisor_operation' in row.message]
        committed = next(event for event in events if event['result'] == 'committed')
        assert committed['created_objects'] == [{'table': 'seo_sites', 'id': 101}]
        assert events[-1]['result'] == 200
    else:
        assert session.new == []
        session.commit.assert_not_called()
