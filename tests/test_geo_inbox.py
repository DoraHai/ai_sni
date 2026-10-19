"""Real HTTP and row-lock tests against only the isolated loopback GEO CI DB."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi import FastAPI
from sqlalchemy import select, text, update, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.schema import CreateIndex, CreateTable

from app.database import get_session
from app.models import (Tenant, TenantModule, GeoProject, User, Role, GeoContentTask,
    GeoArticleVersion, GeoPrompt, GeoOptimizationUnit, GeoOptimizationBusiness, GeoPublication)
from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
from app.models.distribution_inbox import DistributionInboxDevice as Device, DistributionInboxReceipt as Receipt
from app.security.auth import JWT_ALG, _jwt_secret
from app.geo.content import inbox, inbox_policy, inbox_routes
from app.distribution_inbox_protocol import ProtocolError, UUID_PATTERN, match_inbox_business_route, audit_endpoint

DDL = json.loads((Path(__file__).parent/'fixtures/distribution_inbox_ddl.json').read_text(encoding='utf8'))


def test_shared_models_match_authoritative_seo_0110_ddl_exactly():
    statements = [str(CreateTable(m.__table__).compile(dialect=postgresql.dialect())).strip() for m in (Device, Receipt)]
    statements += sorted(str(CreateIndex(i).compile(dialect=postgresql.dialect()))
                         for m in (Device, Receipt) for i in m.__table__.indexes)
    normalize = lambda value: ' '.join(value.split())
    assert [normalize(s) for s in statements] == [normalize(s) for s in DDL['ddl']]


@pytest.mark.parametrize('method,path,expected', [
    ('GET', '/publications', True), ('POST', '/receipts/'+str(uuid4())+'/label', True),
    ('POST', '/receipts/'+str(uuid4())+'/unlabel', True), ('GET', '/publications/', False),
    ('POST', '/publications', False), ('GET', '/publications/extra', False),
    ('POST', '/receipts/Not-A-UUID/label', False),
])
def test_exact_business_menu_routes(method, path, expected):
    from app.security.auth import _required
    path = inbox_routes.PREFIX + path
    assert match_inbox_business_route(method, path, 'geo') is expected
    if expected:
        assert _required(path, method) == ({'geo.content'}, method == 'POST')


def test_audit_paths_hide_real_and_malformed_uuid_values():
    path = inbox_routes.PREFIX+'/receipts/'+str(uuid4())+'/label'
    assert audit_endpoint('POST', path).endswith('/receipts/{uuid}/label')
    assert audit_endpoint('POST', inbox_routes.PREFIX+'/receipts/private-input/label').endswith('/{unmatched}')


def test_frozen_unicode_vectors_preserve_cross_language_bytes():
    from app.distribution_inbox_protocol import canonical_json, payload_digest
    vectors = json.loads((Path(__file__).parent/'fixtures/distribution_inbox_v2_vectors.json').read_text(encoding='utf8'))
    assert vectors['events'][0]['event']['platform'] == '新平台'
    assert '😀' in vectors['events'][0]['event']['title']
    for value in vectors['events']:
        assert canonical_json(value['event']) == value['canonicalJson']
        assert payload_digest(value['event']) == value['event']['payloadDigest']


@pytest.mark.parametrize('sqlstate,constraint,status,code', [
    ('23505','uq_inbox_active_link',409,'DUPLICATE_LINK'),
    ('23503','synthetic_foreign_key',503,'INBOX_SCHEMA_NOT_READY'),
    ('23514','synthetic_check',503,'INBOX_SCHEMA_NOT_READY'),
])
def test_storage_errors_are_sanitized_without_misreporting_unrelated_failures(sqlstate,constraint,status,code):
    from sqlalchemy.exc import IntegrityError
    from unittest.mock import AsyncMock
    from fastapi import HTTPException
    async def run():
        session=NS(rollback=AsyncMock())
        dependency=inbox_routes.safe_session(session)
        await anext(dependency)
        with pytest.raises(HTTPException) as denied:
            await dependency.athrow(IntegrityError('private SQL',{},NS(sqlstate=sqlstate,constraint_name=constraint)))
        assert denied.value.status_code==status and denied.value.detail['code']==code
        assert 'private SQL' not in str(denied.value.detail)
    asyncio.run(run())


def token(uid=11, *, kind='advisor_tenant', tenant=7, grant=1):
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {'sub': str(uid), 'iat': now, 'exp': now+3600}
    if kind:
        claims.update(scope_kind=kind, aud='advisor-business' if kind == 'advisor_tenant' else 'advisor-session')
        if kind == 'advisor_tenant':
            claims.update(tid=tenant, gid=grant, auth_exp=now+3600)
    return jwt.encode(claims, _jwt_secret(), algorithm=JWT_ALG)


@asynccontextmanager
async def sandbox(*, schema_ready=True):
    from ops.run_geo_checks import validate_ci_database
    url = os.environ['GEO_TEST_POSTGRES_URL']; validate_ci_database(url)
    schema = 'geo_inbox_' + uuid4().hex
    engine = create_async_engine(url, connect_args={'server_settings': {
        'search_path': schema, 'lock_timeout': '5000', 'statement_timeout': '15000'}},
        execution_options={'schema_translate_map': {'public': schema}})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI(); app.include_router(inbox_routes.router)
    app.add_middleware(inbox_routes.GeoInboxBoundaryMiddleware)
    async def dependency():
        async with factory() as db:
            yield db
    app.dependency_overrides[get_session] = dependency
    ids = [str(uuid4()) for _ in range(5)]
    now = datetime.now(timezone.utc)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            for model in (Tenant, TenantModule, GeoProject, User, Role, Grant, GeoContentTask,
                GeoArticleVersion, GeoPrompt, GeoOptimizationUnit, GeoOptimizationBusiness, GeoPublication):
                await connection.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
            await connection.execute(text('CREATE TABLE demo_tenant_bindings (tenant_id bigint, demo_tenant_id bigint, '
                'dataset_key varchar(64), dataset_version varchar(40), status varchar(16), version integer)'))
            if schema_ready:
                for statement in DDL['ddl']:
                    await connection.execute(text(statement))
        async with factory() as db:
            db.add_all([Tenant(id=7, name='synthetic GEO only'), Tenant(id=8, name='synthetic other'),
                Role(id=1, name='管理员', is_system=True, permissions={}),
                Role(id=2, name='synthetic GEO advisor', is_system=False, permissions={'geo.assets':'edit','geo.content':'edit'}),
                Role(id=3, name='synthetic account editor', is_system=False, permissions={'settings.accounts':'edit','geo.content':'edit'}),
                Role(id=4, name='synthetic customer', is_system=False, permissions={'geo.content':'view'}),
                User(id=10, username='synthetic-system', password_hash='unusable', role_id=1, is_active=True),
                User(id=11, username='synthetic-owner', password_hash='unusable', role_id=2, tenant_id=7, is_active=True),
                User(id=12, username='synthetic-colleague', password_hash='unusable', role_id=2, tenant_id=7, is_active=True),
                User(id=13, username='synthetic-editor', password_hash='unusable', role_id=3, is_active=True),
                User(id=14, username='synthetic-customer', password_hash='unusable', role_id=4, tenant_id=7, is_active=True),
                TenantModule(id=1, tenant_id=7, module_code='geo', status='active'),
                TenantModule(id=2, tenant_id=8, module_code='geo', status='active'),
                Grant(id=1, user_id=11, tenant_id=7, granted_by=10, grant_source='admin'),
                Grant(id=2, user_id=12, tenant_id=7, granted_by=10, grant_source='admin'),
                GeoProject(id=5, tenant_id=7, tenant_module_id=1, name='synthetic assigned project',
                    primary_domain='example.invalid', canonical_domain='example.invalid', status='active',
                    project_settings={'geo_business_scope': {'revision':1, 'business_ids':[20]},
                                      'geo_service_plan': {'advisor_user_id':11}}),
                GeoOptimizationBusiness(id=20, tenant_id=7, name='synthetic business', status='active'),
                GeoOptimizationUnit(id=20, tenant_id=7, business_id=20, name='synthetic unit', status='active'),
                GeoPrompt(id=30, tenant_id=7, unit_id=20, question='synthetic question', status='active'),
                GeoContentTask(id=40, tenant_id=7, prompt_id=30, business_id=20, title='synthetic task', review_status='approved'),
                GeoArticleVersion(id=50, task_id=40, version_no=1, kind='master', title='synthetic article', body_markdown='synthetic body'),
            ])
            await db.flush()
            if schema_ready:
                device = str(uuid4())
                db.add(Device(id=device, owner_user_id=11, label='synthetic computer', state='active', revision=0,
                    pairing_digest='a'*64, pairing_expires_at=now, created_at=now, rate_buckets={}))
                await db.flush()
                for i, rid in enumerate(ids):
                    url = 'https://example.invalid/article' if i < 2 else 'https://example.invalid/'+str(i)
                    db.add(Receipt(id=rid, owner_user_id=11, device_id=device, event_id=str(uuid4()), attempt_id=str(uuid4()),
                        payload_digest='b'*64, received_at=now, occurred_at=now, platform='unknown-platform',
                        title='synthetic title', reported_account='synthetic reported account', result='success',
                        public_url=url, canonical_url=url, url_hash=hashlib.sha256(url.encode()).hexdigest(),
                        content_bytes=100, normalizer_version='simple-v1', state='pending', label_state='pending', revision=0,
                        verification_status='unlinked', history=[]))
            await db.commit()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            async def request(method, suffix, *, uid=11, kind='advisor_tenant', tenant=7, grant=1, body=None):
                return await client.request(method, inbox_routes.PREFIX+suffix,
                    headers={'Authorization':'Bearer '+token(uid,kind=kind,tenant=tenant,grant=grant)}, json=body)
            yield NS(factory=factory, ids=ids, request=request, client=client)
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


pg = pytest.mark.skipif(not os.getenv('GEO_TEST_POSTGRES_URL'), reason='isolated loopback PostgreSQL required; mandatory in CI')


@pg
def test_geo_only_no_article_projection_owner_and_cross_module_flow(monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), 'advisor_scoped_content_writes_enabled', True)
    async def run():
        async with sandbox() as env:
            rid = env.ids[0]
            response = await env.request('POST', f'/receipts/{rid}/label?tenant_id=7', body={'expectedRevision':0,'targetTenant':7})
            assert response.status_code == 200, response.text
            assert response.json()['assignment']['scopeId'] is None
            assert response.json()['verificationStatus'] == 'unlinked'
            response = await env.request('GET', '/publications?tenant_id=7')
            item = response.json()['items'][0]
            assert item['source'] == 'external_report' and item['platformKind'] == 'other'
            assert not ({'owner_user_id','device_id','event_id','history','attemptId'} & item.keys())
            assert (await env.request('GET', '/publications?tenant_id=7',uid=12,grant=2)).json()['items'] == []
            response = await env.request('POST',f'/receipts/{rid}/label?tenant_id=8',uid=10,kind=None,
                body={'expectedRevision':1,'targetTenant':8})
            assert response.status_code == 409 and response.json()['detail']['code'] == 'CROSS_TARGET_REQUIRES_UNLABEL'
            response = await env.request('POST',f'/receipts/{rid}/unlabel?tenant_id=7',body={'expectedRevision':1,'reason':None})
            assert response.status_code == 200 and response.json()['assignment'] is None
            async with env.factory() as db:
                # A separate module can now label the shared pending row. GEO
                # cannot directly overwrite that SEO target, even as admin.
                row = await db.get(Receipt,rid); row.state = row.label_state = 'active'; row.tenant_id=7; row.module='seo'
                await db.commit()
            response = await env.request('POST',f'/receipts/{rid}/label?tenant_id=7',uid=10,kind=None,
                body={'expectedRevision':2,'targetTenant':7})
            assert response.status_code == 409 and response.json()['detail']['code'] == 'CROSS_TARGET_REQUIRES_UNLABEL'
            async with env.factory() as db:
                assert await db.scalar(select(func.count(GeoPublication.id))) == 0
    asyncio.run(run())


@pg
@pytest.mark.parametrize('scenario', ['other-owner','identity-jwt','account-editor','write-flag','module-disabled','module-expired','grant-revoked','role-changed','project-unassigned','project-foreign','unapproved-article','stale-version','bad-digest'])
def test_permission_and_article_rejections_are_atomic(monkeypatch, scenario):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(),'advisor_scoped_content_writes_enabled',scenario != 'write-flag')
    async def run():
        async with sandbox() as env:
            rid=env.ids[0]; uid=11; kind='advisor_tenant'; grant=1
            body={'expectedRevision':0,'targetTenant':7}
            if scenario == 'other-owner': uid=12; grant=2
            if scenario == 'identity-jwt': kind='advisor_identity'
            if scenario == 'account-editor': uid=13; kind=None
            async with env.factory() as db:
                if scenario == 'module-disabled': await db.execute(update(TenantModule).values(status='inactive'))
                if scenario == 'module-expired': await db.execute(update(TenantModule).values(expires_at=datetime.now().date()-timedelta(days=1)))
                if scenario == 'grant-revoked': await db.execute(update(Grant).where(Grant.id==1).values(revoked_at=datetime.now(timezone.utc),revoked_by=10,revoke_reason='synthetic revoke'))
                if scenario == 'role-changed': await db.execute(update(User).where(User.id==11).values(role_id=3))
                if scenario.startswith('project') or scenario in {'unapproved-article','stale-version','bad-digest'}: body['scopeId']=5
                if scenario == 'project-unassigned': await db.execute(update(GeoProject).values(project_settings={}))
                if scenario == 'project-foreign': body['scopeId']=999
                if scenario in {'unapproved-article','stale-version','bad-digest'}:
                    body.update(articleId=40,articleVersion=1,articleDigest=hashlib.sha256(b'synthetic body').hexdigest())
                if scenario == 'unapproved-article': await db.execute(update(GeoContentTask).values(review_status='pending'))
                if scenario == 'stale-version': body['articleVersion']=2
                if scenario == 'bad-digest': body['articleDigest']='0'*64
                await db.commit()
            response=await env.request('POST',f'/receipts/{rid}/label?tenant_id=7',uid=uid,kind=kind,grant=grant,body=body)
            assert response.status_code in {401,403,404,409}, (scenario,response.text)
            assert response.headers['cache-control']=='no-store'
            if scenario == 'other-owner': assert response.status_code==404
            async with env.factory() as db:
                row=await db.get(Receipt,rid); assert row.revision==0 and row.label_state=='pending' and row.history==[]
    asyncio.run(run())


@pg
def test_concurrent_revision_duplicate_and_fixed_article(monkeypatch):
    from app.config import get_settings
    from app.geo.project_workflows import PLAN_KEY
    monkeypatch.setattr(get_settings(),'advisor_scoped_content_writes_enabled',True)
    async def run():
        async with sandbox() as env:
            async with env.factory() as db:
                project=await db.get(GeoProject,5)
                project.project_settings={**project.project_settings,PLAN_KEY:{'advisor_user_id':11}}
                await db.commit()
            rid=env.ids[0]; data={'expectedRevision':0,'targetTenant':7,'scopeId':5,'articleId':40,'articleVersion':1,
                'articleDigest':hashlib.sha256(b'synthetic body').hexdigest()}
            responses=await asyncio.gather(*(env.request('POST',f'/receipts/{rid}/label?tenant_id=7',body=data) for _ in range(2)))
            assert sorted(r.status_code for r in responses)==[200,409], [r.text for r in responses]
            assert next(r for r in responses if r.status_code==200).json()['verificationStatus']=='unavailable'
            response=await env.request('POST',f'/receipts/{env.ids[1]}/label?tenant_id=7',body={'expectedRevision':0,'targetTenant':7,'scopeId':5})
            assert response.status_code==409 and response.json()['detail']['code']=='DUPLICATE_LINK'
            assert rid not in response.text and 'synthetic-owner' not in response.text
            assert (await env.request('GET','/publications?tenant_id=7&scope_id=5',uid=12,grant=2)).status_code==403
            response=await env.request('POST',f'/receipts/{rid}/unlabel?tenant_id=7',body={'expectedRevision':1,'reason':'synthetic correction'})
            assert response.status_code==200 and response.json()['verificationStatus']=='unlinked'
            assert (await env.request('GET','/publications?tenant_id=7')).json()['total']==0
    asyncio.run(run())


@pg
def test_missing_schema_and_malformed_http_are_safe(monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(),'advisor_scoped_content_writes_enabled',True)
    async def run():
        async with sandbox(schema_ready=False) as env:
            response=await env.request('GET','/publications?tenant_id=7',uid=10,kind=None)
            assert response.status_code==503 and response.json()['detail']['code']=='INBOX_SCHEMA_NOT_READY'
            assert response.headers['cache-control']=='no-store'
        async with sandbox() as env:
            rid=env.ids[0]
            for suffix in ('?tenant_id=7&tenant_id=8','?tenant_id=7&project_id=5','?tenant_id=7&key=forbidden'):
                response=await env.request('POST',f'/receipts/{rid}/label'+suffix,body={'expectedRevision':0,'targetTenant':7})
                assert response.status_code==422, response.text
            response=await env.client.post(inbox_routes.PREFIX+f'/receipts/{rid}/label?tenant_id=7',
                headers={'Authorization':'Bearer '+token()}, content=b'{"expectedRevision":0,"targetTenant":7,"targetTenant":8}')
            assert response.status_code==422 and response.json()['detail']['code']=='INVALID_SHAPE'
            for path in ('/publications/?tenant_id=7','/publications/extra?tenant_id=7','/%70ublications?tenant_id=7'):
                response=await env.request('GET',path)
                assert response.status_code==404 and response.headers['cache-control']=='no-store'
    asyncio.run(run())


@pg
@pytest.mark.parametrize('changed', ['grant','module','project','review'])
def test_postwrite_authority_change_rolls_back_assignment_and_history(monkeypatch, changed):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(),'advisor_scoped_content_writes_enabled',True)
    original=inbox.target_authorized
    async def run():
        async with sandbox() as env:
            calls=0
            async def recheck(db,actor,tenant,scope_id,**kwargs):
                nonlocal calls
                calls+=1
                if calls==2:
                    if changed=='grant': await db.execute(update(Grant).where(Grant.id==1).values(revoked_at=datetime.now(timezone.utc),revoked_by=10,revoke_reason='synthetic race'))
                    if changed=='module': await db.execute(update(TenantModule).values(status='inactive'))
                    if changed=='project': await db.execute(update(GeoProject).values(status='paused'))
                    if changed=='review': await db.execute(update(GeoContentTask).values(review_status='pending'))
                return await original(db,actor,tenant,scope_id,**kwargs)
            data={'expectedRevision':0,'targetTenant':7,'scopeId':5,'articleId':40,'articleVersion':1,
                'articleDigest':hashlib.sha256(b'synthetic body').hexdigest()}
            with patch.object(inbox,'target_authorized',recheck):
                response=await env.request('POST',f'/receipts/{env.ids[0]}/label?tenant_id=7',body=data)
            assert response.status_code==403, response.text
            async with env.factory() as db:
                row=await db.get(Receipt,env.ids[0])
                assert row.revision==0 and row.label_state=='pending' and row.history==[]
    asyncio.run(run())


@pg
def test_unlabel_capacity_and_lost_old_scope_do_not_move_facts(monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(),'advisor_scoped_content_writes_enabled',True)
    async def run():
        async with sandbox() as env:
            rid=env.ids[0]
            response=await env.request('POST',f'/receipts/{rid}/label?tenant_id=7',body={'expectedRevision':0,'targetTenant':7,'scopeId':5})
            assert response.status_code==200, response.text
            with patch.object(inbox,'UNLABELED_ROWS',4):
                response=await env.request('POST',f'/receipts/{rid}/unlabel?tenant_id=7',body={'expectedRevision':1,'reason':None})
                assert response.status_code==429
            async with env.factory() as db:
                await db.execute(update(GeoProject).values(project_settings={}))
                await db.commit()
            response=await env.request('POST',f'/receipts/{rid}/label?tenant_id=7',body={'expectedRevision':1,'targetTenant':7})
            assert response.status_code==403
            response=await env.request('POST',f'/receipts/{rid}/unlabel?tenant_id=7',body={'expectedRevision':1,'reason':None})
            assert response.status_code==403
            response=await env.request('POST',f'/receipts/{rid}/unlabel?tenant_id=7',uid=10,kind=None,body={'expectedRevision':1,'reason':None})
            assert response.status_code==200, response.text
    asyncio.run(run())


@pg
@pytest.mark.parametrize('uid', [13,14])
def test_ineligible_roles_cannot_distinguish_receipt_existence(monkeypatch,uid):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(),'advisor_scoped_content_writes_enabled',True)
    async def run():
        async with sandbox() as env:
            for rid in (env.ids[0],str(uuid4())):
                response=await env.request('POST',f'/receipts/{rid}/label?tenant_id=7',uid=uid,kind=None,
                    body={'expectedRevision':0,'targetTenant':7})
                assert response.status_code==403 and response.json()['detail']['code']=='INBOX_FORBIDDEN'
    asyncio.run(run())


@pg
def test_selected_second_grant_and_current_project_reader(monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(),'advisor_scoped_content_writes_enabled',True)
    async def run():
        async with sandbox() as env:
            async with env.factory() as db:
                db.add(Grant(id=3,user_id=11,tenant_id=8,granted_by=10,grant_source='admin'))
                await db.commit()
            response=await env.request('POST',f'/receipts/{env.ids[0]}/label?tenant_id=8',tenant=8,grant=3,
                body={'expectedRevision':0,'targetTenant':8})
            assert response.status_code==200, response.text
            response=await env.request('POST',f'/receipts/{env.ids[2]}/label?tenant_id=7',
                body={'expectedRevision':0,'targetTenant':7,'scopeId':5})
            assert response.status_code==200, response.text
            async with env.factory() as db:
                project=await db.get(GeoProject,5)
                project.project_settings={**project.project_settings,'geo_service_plan':{'advisor_user_id':12}}
                await db.commit()
            response=await env.request('GET','/publications?tenant_id=7&scope_id=5',uid=12,grant=2)
            assert response.status_code==200 and response.json()['total']==1, response.text
            item=response.json()['items'][0]
            assert not ({'owner_user_id','device_id','event_id','history','attemptId'} & item.keys())
            assert (await env.request('GET','/publications?tenant_id=7&scope_id=5')).status_code==403
    asyncio.run(run())
