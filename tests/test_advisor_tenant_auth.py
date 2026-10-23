"""Actual SQL grant generations + actual JWT + HTTP dependencies, no remote DB."""
import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import jwt
import pytest
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.database import Base, get_session
from app.models.role import Role
from app.models.tenant import Tenant
from app.models.user import User
from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
from app.models.module_workspace import TenantModule, SeoSite
from app.models.seo import SeoSiteAdvisorAssignment
from app.security import auth
from app.security.advisor_seo_scope import is_advisor_role


@compiles(JSONB, 'sqlite')
def sqlite_json(_type, _compiler, **_kw):
    return 'JSON'


class LocalSession:
    """Awaitable facade over SQLite; statements still execute against real SQL."""
    def __init__(self, session):
        self.sync = session

    async def commit(self):
        self.sync.commit()

    async def get(self, *args, **kwargs):
        return self.sync.get(*args, **kwargs)

    async def scalar(self, *args, **kwargs):
        return self.sync.scalar(*args, **kwargs)

    async def scalars(self, *args, **kwargs):
        return self.sync.scalars(*args, **kwargs)

    async def execute(self, *args, **kwargs):
        return self.sync.execute(*args, **kwargs)

    @asynccontextmanager
    async def begin_nested(self):
        with self.sync.begin_nested():
            yield


@pytest.fixture
def local_db(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'advisor.sqlite'))
    models = [Role, Tenant, User, TenantModule, Grant, SeoSite, SeoSiteAdvisorAssignment]
    Base.metadata.create_all(engine, tables=[m.__table__ for m in models])
    with Session(engine, expire_on_commit=False) as s:
        s.add_all([Role(id=1, name='advisor', is_system=False,
                       permissions={'seo.site': 'edit', 'seo.content': 'edit', 'seo.keywords':'view'}),
                   Role(id=2, name='customer', is_system=False, permissions={'seo.site': 'view'}),
                   Role(id=3, name='管理员', is_system=True, permissions={'settings.accounts': 'edit'})])
        for i in (1, 2, 3):
            s.add(Tenant(id=i, name=f'tenant{i}'))
            s.add(TenantModule(id=i, tenant_id=i, module_code='seo', status='active'))
            s.add(SeoSite(id=i, tenant_id=i, tenant_module_id=i, name=f'site{i}',
                          domain=f'example{i}.test', canonical_domain=f'example{i}.test', status='active'))
        for i, role, tid in [(1, 1, 1), (2, 2, 1), (3, 3, None)]:
            s.add(User(id=i, username=f'user{i}', password_hash='unused', role_id=role,
                       tenant_id=tid, is_active=True))
        for gid, tid in [(10, 1), (20, 2)]:
            s.add(Grant(id=gid, user_id=1, tenant_id=tid, granted_by=3, grant_source='admin'))
        s.commit()
        yield s, LocalSession(s)
    engine.dispose()


def claims(**changes):
    now = int(datetime.now(timezone.utc).timestamp())
    return {'sub': '1', 'exp': now+600, 'auth_exp': now+1200, 'scope_kind': 'advisor_tenant',
            'aud': 'advisor-business', 'tid': 1, 'gid': 10, **changes}


def token(payload):
    return jwt.encode(payload, auth._jwt_secret(), algorithm=auth.JWT_ALG)


async def authenticate(session, payload):
    from fastapi.security import HTTPAuthorizationCredentials
    return await auth.require_auth(HTTPAuthorizationCredentials(scheme='Bearer', credentials=token(payload)),
                                   None, None, session)


def test_role_predicate_does_not_depend_on_tenant_or_activation():
    assert is_advisor_role(SimpleNamespace(is_system=False, name='arbitrary',
        permissions={'seo.site':'edit', 'seo.content':'edit'}))
    assert not is_advisor_role(SimpleNamespace(is_system=True, name='管理员',
        permissions={'seo.site':'edit', 'seo.content':'edit'}))
    assert not is_advisor_role(SimpleNamespace(is_system=False, name='advisor',
        permissions={'geo.assets':'edit', 'geo.content':'edit', 'settings.accounts':'edit'}))
    assert not is_advisor_role(SimpleNamespace(is_system=False, name='dirty',
        permissions={'seo.site':'edit', 'seo.content':'edit', 'settings.future':'edit'}))


def test_two_grants_current_context_and_third_tenant_denied(local_db):
    _, session = local_db
    ctx = asyncio.run(authenticate(session, claims()))
    assert ctx.advisor_tenant_ids == {1, 2}
    ctx.ensure_tenant(1)
    for tid in [2, 3, None, True]:
        with pytest.raises(HTTPException) as denied:
            ctx.ensure_tenant(tid)
        assert denied.value.status_code == 403
    assert asyncio.run(authenticate(session, claims(tid=2, gid=20))).tenant_id == 2


def test_revocation_regrant_and_fresh_role_account_reads(local_db):
    db, session = local_db
    assert asyncio.run(authenticate(session, claims())).tenant_id == 1
    grant = db.get(Grant, 10)
    grant.revoked_at = datetime.now(timezone.utc) + timedelta(seconds=1)
    grant.revoked_by, grant.revoke_reason = 3, 'admin_uncheck'
    db.commit()
    with pytest.raises(HTTPException) as denied:
        asyncio.run(authenticate(session, claims()))
    assert denied.value.detail['code'] == 'ADVISOR_GRANT_REVOKED'
    db.add(Grant(id=30, user_id=1, tenant_id=1, granted_by=3, grant_source='admin'))
    db.commit()
    with pytest.raises(HTTPException):
        asyncio.run(authenticate(session, claims()))
    assert asyncio.run(authenticate(session, claims(gid=30))).grant_id == 30
    db.get(User, 1).locked_until = datetime.now() + timedelta(hours=1)
    db.commit()
    with pytest.raises(HTTPException) as denied:
        asyncio.run(authenticate(session, claims(gid=30)))
    assert denied.value.status_code == 401
    db.get(User, 1).locked_until = None
    db.get(User, 1).role_id = 2
    db.commit()
    with pytest.raises(HTTPException) as denied:
        asyncio.run(authenticate(session, claims(gid=30)))
    assert denied.value.detail['code'] == 'ADVISOR_ROLE_CHANGED'


@pytest.mark.parametrize('change', [{'gid': True}, {'tid': -1}, {'aud':'advisor-session'},
    {'auth_exp':True}, {'auth_exp':1}, {'exp':True}, {'scope_kind':'unknown'}, {'sub':'nope'}])
def test_malformed_tokens_rejected(local_db, change):
    with pytest.raises(HTTPException):
        asyncio.run(authenticate(local_db[1], claims(**change)))


def test_legacy_switch_rejected_even_with_old_flag_enabled(local_db):
    with pytest.raises(HTTPException) as denied:
        asyncio.run(authenticate(local_db[1], claims(via='advisor_switch')))
    assert denied.value.status_code == 401


def test_legacy_advisor_requires_selection_even_with_backfilled_default(local_db):
    with pytest.raises(HTTPException) as denied:
        asyncio.run(authenticate(local_db[1], {'sub':'1','exp':claims()['exp']}))
    assert denied.value.detail['code'] == 'ADVISOR_TENANT_SELECTION_REQUIRED'


def test_identity_tenant_list_reads_latest_intersection_never_all(local_db):
    from app.api.auth import list_tenants
    db, session = local_db
    identity = claims(scope_kind='advisor_identity', aud='advisor-session')
    async def listing():
        ctx = await authenticate(session, identity)
        return await list_tenants(ctx, session)
    assert [t['id'] for t in asyncio.run(listing())['tenants']] == [1, 2]
    db.execute(text("UPDATE advisor_tenant_grants SET revoked_at=CURRENT_TIMESTAMP,revoked_by=3,revoke_reason='admin_uncheck'"))
    db.get(User,1).tenant_id=None
    db.commit()
    assert asyncio.run(listing()) == {'tenants': []}


def test_missing_table_advisor_503_customer_admin_unchanged(local_db):
    db, session = local_db
    db.execute(text('DROP TABLE advisor_tenant_grants'))
    db.commit()
    with pytest.raises(HTTPException) as denied:
        asyncio.run(authenticate(session, claims()))
    assert denied.value.status_code == 503
    for user_id, tenant_id in [(2, 1), (3, None)]:
        ctx = asyncio.run(authenticate(session, {'sub':str(user_id), 'exp':claims()['exp']}))
        assert not ctx.is_advisor and ctx.tenant_id == tenant_id


def test_permission_failure_is_closed(local_db):
    from sqlalchemy.exc import DBAPIError
    session = local_db[1]
    with patch.object(session, 'scalars', AsyncMock(side_effect=DBAPIError('SELECT', {}, Exception('denied')))):
        with pytest.raises(HTTPException) as denied:
            asyncio.run(authenticate(session, claims()))
    assert denied.value.detail['code'] == 'ADVISOR_GRANTS_UNAVAILABLE'


@pytest.mark.parametrize('failure', ['missing_table', 'permission'])
@pytest.mark.parametrize('tenant_id', [1, None])
def test_no_table_phase_non_advisor_scope_is_unchanged(local_db, failure, tenant_id):
    from sqlalchemy.exc import DBAPIError
    db, session = local_db
    db.get(User, 2).tenant_id = tenant_id
    db.commit()
    if failure == 'missing_table':
        db.execute(text('DROP TABLE advisor_tenant_grants'))
        db.commit()
        ctx = asyncio.run(authenticate(session, {'sub':'2', 'exp':claims()['exp']}))
    else:
        with patch.object(session, 'scalars', AsyncMock(side_effect=DBAPIError(
                'SELECT', {}, Exception('denied')))):
            ctx = asyncio.run(authenticate(session, {'sub':'2', 'exp':claims()['exp']}))
    assert not ctx.is_advisor and ctx.tenant_id == tenant_id
    # Failed grants reads must leave the ordinary request transaction usable.
    assert asyncio.run(session.scalar(select(User.id).where(User.id == 2))) == 2


def test_http_identity_empty_idor_duplicates_module_and_writes(local_db):
    db, session = local_db
    app = FastAPI()
    async def local_session():
        yield session
    app.dependency_overrides[get_session] = local_session

    @app.get('/api/v1/seo/site-pages/{page_id}')
    @app.get('/api/v1/seo/keywords')
    @app.get('/api/v1/auth/me')
    @app.post('/api/v1/seo/content-distribution/publish')
    async def handler(ctx=Depends(auth.require_auth)):
        return {'tenant':ctx.tenant_id}

    @app.get('/api/v1/seo/sites/{site_id}')
    async def site(ctx=Depends(auth.require_auth)):
        return {'tenant':ctx.tenant_id}

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://local.test') as client:
            async def get(path, payload=None):
                return await client.get(path, headers={'Authorization':'Bearer '+token(payload or claims())})
            assert (await get('/api/v1/seo/keywords?tenant_id=1')).status_code == 200
            assert (await get('/api/v1/seo/keywords?tenant_id=3')).status_code == 403
            assert (await get('/api/v1/seo/keywords?tenant_id=3&tenant_id=1')).status_code == 422
            assert (await get('/api/v1/seo/sites/3?tenant_id=1')).status_code == 403
            assert (await get('/api/v1/seo/sites/2?tenant_id=1')).status_code == 403
            assert (await get('/api/v1/seo/keywords?tenant_id=1&unregistered_id=3')).status_code == 403
            assert (await get('/api/v1/seo/keywords')).status_code == 403
            identity = claims(scope_kind='advisor_identity', aud='advisor-session')
            assert (await get('/api/v1/auth/me', identity)).status_code == 200
            assert (await get('/api/v1/seo/keywords?tenant_id=1', identity)).status_code == 409
            assert (await client.post('/api/v1/seo/content-distribution/publish', json={'tenant_id':1},
                headers={'Authorization':'Bearer '+token(claims())})).status_code == 403
            db.get(TenantModule,1).expires_at=date.today()-timedelta(days=1)
            db.commit()
            assert (await get('/api/v1/seo/keywords?tenant_id=1')).status_code == 403
            db.get(TenantModule,1).expires_at=None
            db.commit()
            db.execute(text("UPDATE advisor_tenant_grants SET revoked_at=CURRENT_TIMESTAMP, revoked_by=3, revoke_reason='admin_uncheck'"))
            db.get(User, 1).tenant_id = None
            db.commit()
            assert (await get('/api/v1/seo/keywords?tenant_id=1', identity)).status_code == 403
            assert (await get('/api/v1/auth/me', identity)).status_code == 200
    asyncio.run(scenario())


@pytest.mark.parametrize('revision', ['0108_advisor_account_links', '0109_advisor_tenant_grants', '0110_distribution_inbox', '0111_geo_autopatrol'])
def test_old_and_new_revision_keep_all_existing_health_structure_checks(revision):
    from app import seo_main
    from test_seo_deploy_isolation import _HealthEngine
    checks = ['_check_seo_structure', '_check_geo_ticket_adoption', '_check_demo_binding_structure',
              '_check_geo_review_audit', '_check_capture_structure',
              '_check_content_confirmation_structure', '_check_content_message_structure']
    from contextlib import ExitStack
    with ExitStack() as stack:
        stack.enter_context(patch.object(seo_main, 'engine', _HealthEngine([revision])))
        # Message inspection uses PostgreSQL's native Inspector; its native test
        # suite covers shape, while this offline harness proves branch selection.
        mocks = [stack.enter_context(patch.object(seo_main, name, AsyncMock(
            wraps=None if name == '_check_content_message_structure' else getattr(seo_main,name)))) for name in checks]
        response = Response()
        result = asyncio.run(seo_main.seo_health(response))
        assert response.status_code == 200 and result['schema'] == 'ok', result
        assert all(m.await_count == 1 for m in mocks)


@pytest.mark.parametrize('revision', ['0109_advisor_tenant_grants', '0110_distribution_inbox', '0111_geo_autopatrol'])
def test_0109_health_rejects_missing_grant_shape(revision):
    from app import seo_main
    from test_seo_deploy_isolation import _HealthEngine, _HealthConnection
    original = _HealthConnection.execute
    async def missing_columns(self, statement, parameters=None):
        if 'advisor_tenant_grants' in str(statement) and 'pg_attribute' in str(statement):
            return []
        return await original(self, statement, parameters)
    with (patch.object(seo_main,'engine',_HealthEngine([revision])),
          patch.object(_HealthConnection,'execute',missing_columns),
          patch.object(seo_main,'_check_content_message_structure',AsyncMock())):
        response=Response()
        result=asyncio.run(seo_main.seo_health(response))
        assert response.status_code==503
        assert 'Advisor grant table' in result['db_error']


@pytest.fixture
def advisor_queue(local_db):
    """Real queue + grant SQL; only credential verification is supplied locally.

    No signed tokens, external database or provider calls are needed.
    """
    from app.api import seo_onsite_ai as api
    from app.models.seo import SeoSiteAdvisorAssignment
    from app.models.seo_cockpit import SeoTask
    from app.security.advisor_tenant_auth import apply_advisor_claims, enforce_advisor_request
    from sqlalchemy.dialects.sqlite.base import SQLiteCompiler

    class QueueCompiler(SQLiteCompiler):
        def visit_custom_op_binary(self, binary, operator, **kw):
            sql = super().visit_custom_op_binary(binary, operator, **kw)
            # PostgreSQL ->> always returns text; SQLite returns an int for 1.
            return f'CAST({sql} AS TEXT)' if operator.opstring == '->>' else sql

    db, session = local_db
    db.get_bind().dialect.statement_compiler = QueueCompiler
    Base.metadata.create_all(db.get_bind(), tables=[
        SeoSiteAdvisorAssignment.__table__, SeoTask.__table__])
    db.add_all([
        Tenant(id=15, name='local customer 15'),
        TenantModule(id=15, tenant_id=15, module_code='seo', status='active'),
        SeoSite(id=15, tenant_id=15, tenant_module_id=15, name='local site',
                domain='example.test', canonical_domain='example.test', status='active'),
        Grant(id=30, user_id=1, tenant_id=15, granted_by=3, grant_source='admin'),
        SeoSiteAdvisorAssignment(id=15, tenant_id=15, site_id=15, advisor_user_id=1, active=True),
        SeoTask(id=15, tenant_id=15, site_id=15, module='seo', action_type='onsite_optimization',
                title='local onsite task', created_by='1', assignee_role='seo_advisor',
                params={'onsite': {'schema': 1, 'module': 'seo', 'revision': 1,
                                  'phase': 'draft', 'items': [], 'history': []}}),
    ])
    db.get(User, 1).tenant_id = 15
    db.commit()
    identity = {'user_id': 1, 'claims': claims(tid=15, gid=30)}
    app = FastAPI()
    app.include_router(api.router, prefix='/api/v1/seo')

    async def guarded(request: Request):
        user = await session.get(User, identity['user_id'])
        role = await session.get(Role, user.role_id)
        ctx = auth.AuthContext(user.id, user.username, role.name, user.tenant_id, role.permissions,
                               is_superadmin=role.is_system and role.name == '管理员')
        await apply_advisor_claims(ctx, user, role, identity['claims'], session)
        await enforce_advisor_request(request, ctx, session)
        return await auth.enforce_scoped_request(request, ctx)

    app.dependency_overrides[api.get_seo_session] = lambda: session
    app.dependency_overrides[api.require_seo_scoped_auth] = guarded
    return app, db, identity


def test_advisor_queue_selected_tenant15_assignment_and_non_advisors(advisor_queue):
    app, db, identity = advisor_queue

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://local.test') as client:
            path = '/api/v1/seo/workbench/advisor-tasks?limit=25&tenant_id=15'
            response = await client.get(path)
            assert response.status_code == 200
            assert [row['id'] for row in response.json()['items']] == [15]
            assert response.json()['items'][0]['tenant_id'] == 15
            # Assignment removal still hides all tasks, even with a tenant grant.
            from app.models.seo import SeoSiteAdvisorAssignment
            db.get(SeoSiteAdvisorAssignment, 15).active = False
            db.commit()
            assert (await client.get(path)).json()['items'] == []
            for uid, tid in [(2, 1), (3, 15)]:
                identity.update(user_id=uid, claims={})
                response = await client.get(f'/api/v1/seo/workbench/advisor-tasks?tenant_id={tid}')
                assert response.status_code == 200 and response.json()['items'] == []
    asyncio.run(scenario())


@pytest.mark.parametrize('case,status,code', [
    ('no_grants', 403, 'ADVISOR_NO_TENANT'),
    ('not_selected', 409, 'ADVISOR_TENANT_SELECTION_REQUIRED'),
    ('missing_tenant', 403, 'ADVISOR_TENANT_REQUIRED'),
    ('foreign_tenant', 403, 'ADVISOR_TENANT_NOT_GRANTED'),
    ('other_granted_tenant', 403, 'ADVISOR_TENANT_NOT_GRANTED'),
    ('revoked', 401, 'ADVISOR_GRANT_REVOKED'),
    ('role_changed', 403, 'ADVISOR_ROLE_CHANGED'),
    ('module_expired', 403, None),
])
def test_advisor_queue_denials_remain_closed(advisor_queue, case, status, code):
    app, db, identity = advisor_queue
    path = '/api/v1/seo/workbench/advisor-tasks?tenant_id=15'
    if case in {'no_grants', 'not_selected'}:
        identity['claims'] = claims(scope_kind='advisor_identity', aud='advisor-session')
        if case == 'no_grants':
            for grant in db.scalars(select(Grant)):
                grant.revoked_at = datetime.now(timezone.utc)
                grant.revoked_by, grant.revoke_reason = 3, 'admin_uncheck'
    elif case == 'missing_tenant':
        path = path.split('?')[0]
    elif case in {'foreign_tenant', 'other_granted_tenant'}:
        path = path.replace('tenant_id=15', 'tenant_id=3' if case == 'foreign_tenant' else 'tenant_id=2')
    elif case == 'revoked':
        grant = db.get(Grant, 30)
        grant.revoked_at = datetime.now(timezone.utc)
        grant.revoked_by, grant.revoke_reason = 3, 'admin_uncheck'
    elif case == 'role_changed':
        db.get(User, 1).role_id = 2
    elif case == 'module_expired':
        db.get(TenantModule, 15).expires_at = date.today() - timedelta(days=1)
    db.commit()

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://local.test') as client:
            response = await client.get(path)
            assert response.status_code == status
            if code:
                assert response.json()['detail']['code'] == code
    asyncio.run(scenario())


def test_advisor_queue_mapping_is_exact_get_only_and_ai_writes_stay_disabled(advisor_queue):
    app, _, _ = advisor_queue
    path = '/api/v1/seo/workbench/advisor-tasks'
    assert auth._required(path, 'GET') == ({'seo.content', 'seo.site'}, False)
    for method in ['POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']:
        assert auth._required(path, method)[0] is None
    for suffix in ['/', '/extra', '-extra']:
        assert auth._required(path + suffix, 'GET')[0] is None

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://local.test') as client:
            response = await client.post('/api/v1/seo/workbench/onsite-tasks/15/ai-proposal', json={
                'tenant_id': 15, 'site_id': 15, 'expected_revision': 1,
                'request_id': '00000000-0000-4000-8000-000000000001', 'mode': 'initial'})
            assert response.status_code == 403
            assert response.json()['detail']['code'] == 'ADVISOR_HIGH_RISK_WRITES_DISABLED'
    asyncio.run(scenario())


def _read_guard_request(route, params):
    from urllib.parse import urlencode
    return Request({'type': 'http', 'method': 'GET', 'path': route,
                    'headers': [],
                    'query_string': urlencode(params, doseq=True).encode(),
                    'path_params': {}, 'route': SimpleNamespace(path=route)})


def _read_guard_context():
    return auth.AuthContext(1, 'synthetic', 'advisor', 1,
        {'seo.site': 'edit', 'seo.content': 'edit'}, is_advisor=True,
        scope_kind='advisor_tenant', grant_id=10, advisor_tenant_ids=frozenset({1}))


@pytest.mark.parametrize('route,key', [
    ('/api/v1/seo/workbench/advisor-tasks', 'before_id'),
    ('/api/v1/seo/site-pages/index-reviews', 'before_id'),
    ('/api/v1/seo/site-pages/image-remediation-history', 'before_snapshot_id'),
])
def test_read_guard_numeric_cursors_do_not_query_unrelated_messages(route, key):
    from app.security.advisor_tenant_auth import check_seo_objects
    session = SimpleNamespace(scalar=AsyncMock(return_value=None))
    request = _read_guard_request(route, {'tenant_id': 1, key: 500})
    asyncio.run(check_seo_objects(request, _read_guard_context(), session))
    session.scalar.assert_not_awaited()


@pytest.mark.parametrize('route,key,table,extra', [
    ('/api/v1/seo/site-pages/image-evidence', 'snapshot_id', 'seo_page_snapshots', {}),
    ('/api/v1/seo/site-pages/image-remediation', 'snapshot_id', 'seo_page_snapshots', {}),
    ('/api/v1/seo/qa/research/history', 'answer_id', 'seo_qa_answers', {}),
    ('/api/v1/seo/site/page-captures', 'relation_id', 'seo_site_pages', {'relation_type': 'site_page'}),
    ('/api/v1/seo/site/page-captures', 'relation_id', 'seo_content_publications', {'relation_type': 'publication'}),
])
@pytest.mark.parametrize('owner,status', [(1, None), (2, 403), (None, 404)])
def test_read_guard_supported_filters_recheck_actual_owner(route, key, table, extra, owner, status):
    from app.security.advisor_tenant_auth import check_seo_objects
    session = SimpleNamespace(scalar=AsyncMock(return_value=owner))
    request = _read_guard_request(route, {'tenant_id': 1, key: 50, **extra})
    if status is None:
        asyncio.run(check_seo_objects(request, _read_guard_context(), session))
    else:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(check_seo_objects(request, _read_guard_context(), session))
        assert exc.value.status_code == status
    assert table in str(session.scalar.await_args.args[0])


@pytest.mark.parametrize('params', [
    {'relation_id': 50},
    {'relation_id': 50, 'relation_type': 'unknown'},
    {'relation_id': 50, 'relation_type': ['site_page', 'publication']},
    {'before_id': 50},
    {'future_id': 50},
])
def test_read_guard_unknown_or_ambiguous_selectors_remain_closed(params):
    from app.security.advisor_tenant_auth import check_seo_objects
    session = SimpleNamespace(scalar=AsyncMock())
    request = _read_guard_request('/api/v1/seo/site/page-captures', {'tenant_id': 1, **params})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(check_seo_objects(request, _read_guard_context(), session))
    assert exc.value.status_code in {403, 422}
    session.scalar.assert_not_awaited()


def test_read_guard_message_cursor_still_checks_conversation_owner():
    from app.security.advisor_tenant_auth import check_seo_objects
    session = SimpleNamespace(scalar=AsyncMock(return_value=2))
    request = _read_guard_request(
        '/api/v1/seo/workbench/content-assets/{content_id}/conversation/messages',
        {'tenant_id': 1, 'before_id': 50})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(check_seo_objects(request, _read_guard_context(), session))
    assert exc.value.status_code == 403
    query = str(session.scalar.await_args.args[0])
    assert 'seo_content_messages' in query and 'seo_content_conversations' in query


def test_read_guard_repeated_object_ids_are_all_checked():
    from app.security.advisor_tenant_auth import check_seo_objects
    # Each accepted owner now also checks the assignment-scoped object query.
    session = SimpleNamespace(scalar=AsyncMock(side_effect=[1, 50, 2]))
    request = _read_guard_request('/api/v1/seo/site-pages/image-evidence',
                                  {'tenant_id': 1, 'snapshot_id': [50, 51]})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(check_seo_objects(request, _read_guard_context(), session))
    assert exc.value.status_code == 403
    assert session.scalar.await_count == 3

def test_read_guard_queue_keeps_selected_nondefault_granted_tenant():
    from app.api import seo_onsite_ai as api
    from sqlalchemy.dialects import postgresql
    ctx = _read_guard_context()
    ctx.tenant_id, ctx.grant_id, ctx.advisor_tenant_ids = 2, 20, frozenset({1, 2})
    user = SimpleNamespace(id=1, username='synthetic', role_id=1, tenant_id=1,
                           is_active=True, locked_until=None)
    role = SimpleNamespace(id=1, name='advisor', is_system=False,
                           permissions={'seo.site': 'edit', 'seo.content': 'edit'})
    session = SimpleNamespace(get=AsyncMock(side_effect=[user, role]),
                              execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [])))
    result = asyncio.run(api.advisor_tasks(before_id=500, limit=20, tenant_id=2, session=session, ctx=ctx))
    assert result['items'] == []
    query = session.execute.await_args.args[0]
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))
    assert 'seo_tasks.tenant_id = 2' in sql
    assert 'advisor_tenant_grants.tenant_id = 2' in sql
    assert 'advisor_tenant_grants.revoked_at IS NULL' in sql
    assert 'seo_site_advisor_assignments.active IS true' in sql
    assert 'users.tenant_id' not in sql
    assert 'seo_tasks.id < 500' in sql


@pytest.mark.parametrize('case,code', [('role_changed', 'ADVISOR_ROLE_CHANGED'),
    ('locked', 'ADVISOR_GRANT_REVOKED'), ('invalid_default', 'ADVISOR_DEFAULT_TENANT_INVALID')])
def test_read_guard_queue_fresh_identity_checks_remain_closed(case, code):
    from app.api import seo_onsite_ai as api
    ctx = _read_guard_context()
    user = SimpleNamespace(id=1, username='synthetic', role_id=1, tenant_id=1,
                           is_active=True, locked_until=None)
    role = SimpleNamespace(id=1, name='advisor', is_system=False,
                           permissions={'seo.site': 'edit', 'seo.content': 'edit'})
    if case == 'role_changed':
        role.permissions = {'seo.site': 'view'}
    elif case == 'locked':
        user.locked_until = datetime.now(timezone.utc) + timedelta(hours=1)
    else:
        user.tenant_id = 99
    session = SimpleNamespace(get=AsyncMock(side_effect=[user, role]))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.fresh_context(session, ctx))
    assert exc.value.detail['code'] == code


def test_read_guard_queue_ordinary_account_keeps_default_tenant_filter():
    from app.api import seo_onsite_ai as api
    from sqlalchemy.dialects import postgresql
    sql = str(api.advisor_query(7).compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))
    assert 'users.tenant_id IS NULL' in sql
    assert 'users.tenant_id = seo_tasks.tenant_id' in sql
    assert 'advisor_tenant_grants' not in sql
