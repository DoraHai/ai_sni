"""Actual SQL grant generations + actual JWT + HTTP dependencies, no remote DB."""
import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import jwt
import pytest
from fastapi import Depends, FastAPI, HTTPException, Response
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
from app.security import auth
from app.security.advisor_scope import is_advisor_role


@compiles(JSONB, 'sqlite')
def sqlite_json(_type, _compiler, **_kw):
    return 'JSON'


class LocalSession:
    """Awaitable facade over SQLite; statements still execute against real SQL."""
    def __init__(self, session):
        self.sync = session

    async def get(self, *args, **kwargs):
        return self.sync.get(*args, **kwargs)

    async def scalar(self, *args, **kwargs):
        return self.sync.scalar(*args, **kwargs)

    async def scalars(self, *args, **kwargs):
        return self.sync.scalars(*args, **kwargs)

    @asynccontextmanager
    async def begin_nested(self):
        with self.sync.begin_nested():
            yield


@pytest.fixture
def local_db(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'advisor.sqlite'))
    models = [Role, Tenant, User, TenantModule, Grant, SeoSite]
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
    # SQLite does not support the PostgreSQL partial index on this test fixture.
    db.execute(text('DROP INDEX uq_advisor_tenant_grants_active'))
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


@pytest.mark.parametrize('revision', ['0108_advisor_account_links', '0109_advisor_tenant_grants'])
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


def test_0109_health_rejects_missing_grant_shape():
    from app import seo_main
    from test_seo_deploy_isolation import _HealthEngine, _HealthConnection
    original = _HealthConnection.execute
    async def missing_columns(self, statement, parameters=None):
        if 'advisor_tenant_grants' in str(statement) and 'pg_attribute' in str(statement):
            return []
        return await original(self, statement, parameters)
    with (patch.object(seo_main,'engine',_HealthEngine(['0109_advisor_tenant_grants'])),
          patch.object(_HealthConnection,'execute',missing_columns),
          patch.object(seo_main,'_check_content_message_structure',AsyncMock())):
        response=Response()
        result=asyncio.run(seo_main.seo_health(response))
        assert response.status_code==503
        assert 'Advisor grant table' in result['db_error']
