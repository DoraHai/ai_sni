"""Required real PG/HTTP/SQL concurrency coverage; synthetic identities only."""
import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi import FastAPI
from sqlalchemy import select, text, func
from sqlalchemy.schema import CreateTable
from alembic.operations import Operations
from alembic.migration import MigrationContext

from app.api.distribution_inbox import router, _claim_rates
from app.database import get_session
from app.distribution_inbox_protocol import PREFIX as I, payload_digest
from app import distribution_inbox_service as svc
from app.models.distribution_inbox import DistributionInboxDevice as Device, DistributionInboxReceipt as Receipt
from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
from app.models.role import Role
from app.models.user import User
from app.models.tenant import Tenant
from app.models.module_workspace import TenantModule, SeoSite
from app.models.seo import SeoSiteAdvisorAssignment, SeoContentAsset, SeoContentConfirmation
from app.security import auth
from test_seo_workflow_postgres import database


def revision():
    spec = importlib.util.spec_from_file_location('inbox_revision', Path(__file__).parents[1]/'migrations/versions/20261019_0110_distribution_inbox.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def token(uid=7, *, business=False, tenant=4, grant=10, admin=False):
    exp = int(svc.now().timestamp())+3600
    claims = {} if admin else {'aud':'advisor-business' if business else 'advisor-session',
        'scope_kind':'advisor_tenant' if business else 'advisor_identity'}
    if business:
        claims.update(tid=tenant, gid=grant, auth_exp=exp)
    return {'Authorization': 'Bearer '+jwt.encode({'sub':str(uid),'exp':exp,**claims}, auth._jwt_secret(), algorithm='HS256')}


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setattr(auth.get_settings(), 'advisor_scoped_content_writes_enabled', True)
    _claim_rates.clear()


@asynccontextmanager
async def harness(*, tables=True):
    async with database() as sessions:
        async with sessions() as session:
            await session.execute(CreateTable(Grant.__table__, include_foreign_key_constraints=[]))
            session.add_all([
                Role(id=9, name='管理员', is_system=True, permissions={'seo.content':'edit','settings.accounts':'edit'}),
                User(id=9, username='synthetic-admin', password_hash='unused', role_id=9, is_active=True),
                User(id=8, username='synthetic-peer', password_hash='unused', role_id=5, tenant_id=4, is_active=True),
                Grant(id=10, user_id=7, tenant_id=4, granted_by=9, grant_source='admin'),
                Grant(id=11, user_id=8, tenant_id=4, granted_by=9, grant_source='admin'),
                Tenant(id=5, name='synthetic-other'),
                SeoSite(id=3, tenant_id=4, tenant_module_id=1, name='unassigned', domain='other.invalid', canonical_domain='other.invalid', status='active'),
            ])
            (await session.get(User, 7)).tenant_id = 4
            await session.commit()
            if tables:
                conn = await session.connection()
                def upgrade(sync):
                    with Operations.context(MigrationContext.configure(sync)):
                        revision().upgrade()
                await conn.run_sync(upgrade)
                await session.commit()
        app = FastAPI()
        app.include_router(router)
        async def local():
            async with sessions() as session:
                yield session
        app.dependency_overrides[get_session] = local
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://synthetic.invalid') as client:
            yield sessions, client


async def paired(client, headers=None):
    headers = headers or token()
    created = await client.post(I+'/pairings', json={}, headers=headers)
    assert created.status_code == 201, created.text
    row = created.json()
    claimed = await client.post(I+'/device-pairings/claim', json={'pairingCode':row['pairingCode'], 'requestId':str(uuid4())})
    assert claimed.status_code == 200, claimed.text
    return row, claimed.json(), {'Authorization':'Bearer '+claimed.json()['credential']}


def event(**changes):
    e = {'schema':2, 'eventId':str(uuid4()), 'attemptId':str(uuid4()), 'occurredAt':svc.iso(svc.now()),
        'platform':'未知平台😀', 'title':'合成标题', 'reportedAccount':'合成账号', 'result':'success',
        'reasonCode':None, 'publicUrl':'http://Example.invalid/post#part', 'reviewed':True, **changes}
    e['payloadDigest'] = payload_digest(e)
    return e


async def sent(client, headers, **changes):
    e = event(**changes)
    r = await client.post(I+'/device/results', json=e, headers=headers)
    assert r.status_code == 200, r.text
    return e, r.json()


async def label(client, rid, *, headers=None, scope=2, revision=0, **changes):
    return await client.post('/api/v1/seo/distribution/v2/receipts/'+rid+'/label?tenant_id=4',
        headers=headers or token(business=True), json={'expectedRevision':revision, 'targetTenant':4, 'scopeId':scope, **changes})


def test_no_channel_pairing_once_concurrent_digest_and_exact_ack_tombstone(monkeypatch):
    async def scenario():
        async with harness() as (sessions, c):
            _, device, dh = await paired(c)
            body = event()
            replies = await asyncio.gather(*(c.post(I+'/device/results',json=body,headers=dh) for _ in range(8)))
            assert all(r.status_code == 200 for r in replies)
            assert all(r.json() == replies[0].json() for r in replies)
            ack = replies[0].json()
            assert set(ack) == {'schema','eventId','deviceId','payloadDigest','receiptId','receivedAt'}
            changed = event(eventId=body['eventId'], title='changed')
            assert (await c.post(I+'/device/results',json=changed,headers=dh)).status_code == 409
            assert (await c.get(I+'/receipts',headers=token(8))).json()['total'] == 0
            assert (await c.get(I+'/receipts/'+ack['receiptId'],headers=token(8))).status_code == 404
            detail = (await c.get(I+'/receipts/'+ack['receiptId'], headers=token())).json()
            assert detail['platform'] == '未知平台😀' and detail['platformKind'] == 'other'
            assert detail['publicUrl'] == 'http://example.invalid/post'
            assert (await c.post(I+'/receipts/'+ack['receiptId']+'/archive',json={'expectedRevision':0},headers=token())).status_code == 200
            assert (await c.post(I+'/receipts/'+ack['receiptId']+'/delete',json={'expectedRevision':1},headers=token())).status_code == 200
            monkeypatch.setattr(svc, 'TOTAL_ROWS', 1)
            assert (await c.post(I+'/device/results',json=body,headers=dh)).json() == ack
            assert (await c.post(I+'/device/ack',json={k:body[k] for k in ('schema','eventId','payloadDigest')},headers=dh)).json() == ack
            assert (await c.post(I+'/device/results',json=event(),headers=dh)).status_code == 429
            async with sessions() as s:
                saved = await s.get(Receipt, ack['receiptId'])
                assert saved.title is None and saved.public_url is None and saved.deleted_at
                assert saved.payload_digest == body['payloadDigest']
                d = await s.get(Device, device['deviceId'])
                assert d.credential_digest != device['credential'] and not hasattr(d,'credential')
    asyncio.run(scenario())


def test_claim_race_uses_one_time_high_entropy_code():
    async def scenario():
        async with harness() as (_, c):
            p = (await c.post(I+'/pairings',json={},headers=token())).json()
            assert len(p['pairingCode']) == 37 and p['pairingCode'].startswith('DHT2-')
            req = {'pairingCode':p['pairingCode'],'requestId':str(uuid4())}
            replies = await asyncio.gather(*(c.post(I+'/device-pairings/claim',json=req) for _ in range(8)))
            assert sorted(r.status_code for r in replies) == [200]+[409]*7
            assert (await c.post(I+'/device-pairings/claim',json=req)).status_code == 409
            p = (await c.post(I+'/pairings',json={},headers=token())).json()
            assert (await c.post(I+'/pairings/'+p['pairingId']+'/cancel',json={'expectedRevision':0},headers=token())).status_code == 200
            assert (await c.post(I+'/device-pairings/claim',json={'pairingCode':p['pairingCode'],'requestId':str(uuid4())})).status_code == 409
    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['disabled','locked','role','expired','revoked'])
def test_device_rechecks_current_owner_and_revocation_for_events_and_ack(change):
    async def scenario():
        async with harness() as (sessions, c):
            _, d, dh = await paired(c)
            e, _ = await sent(c, dh)
            async with sessions() as s:
                u = await s.get(User,7)
                row = await s.get(Device,d['deviceId'])
                if change == 'disabled': u.is_active = False
                if change == 'locked': u.locked_until = (svc.now()+timedelta(hours=1)).replace(tzinfo=None)
                if change == 'role': u.role_id = 9
                if change == 'expired': row.credential_expires_at = svc.now()-timedelta(seconds=1)
                if change == 'revoked': row.state = 'revoked'
                # role -> administrator is still eligible, then remove qualification.
                if change == 'role':
                    s.add(Role(id=12,name='customer',permissions={'seo.content':'view'})); u.role_id = 12
                await s.commit()
            assert (await c.post(I+'/device/results',json=e,headers=dh)).status_code == 401
            assert (await c.post(I+'/device/ack',json={k:e[k] for k in ('schema','eventId','payloadDigest')},headers=dh)).status_code == 401
    asyncio.run(scenario())


@pytest.mark.parametrize('limit', ['UNLABELED_ROWS','UNLABELED_BYTES','TOTAL_ROWS','TOTAL_BYTES'])
def test_capacity_race_rejects_without_ack_and_replay_survives(limit, monkeypatch):
    async def scenario():
        async with harness() as (sessions, c):
            _, _, dh = await paired(c)
            monkeypatch.setattr(svc, limit, 1 if limit.endswith('ROWS') else 700)
            bodies = [event(publicUrl='https://example.invalid/'+str(i)) for i in range(4)]
            replies = await asyncio.gather(*(c.post(I+'/device/results',json=e,headers=dh) for e in bodies))
            assert sum(r.status_code == 200 for r in replies) == 1, [r.text for r in replies]
            assert sum(r.status_code == 429 for r in replies) == 3
            async with sessions() as s:
                assert await s.scalar(select(func.count()).select_from(Receipt)) == 1
            for e,r in zip(bodies,replies):
                if r.status_code == 200:
                    assert (await c.post(I+'/device/results',json=e,headers=dh)).json() == r.json()
                else:
                    a = await c.post(I+'/device/ack',json={k:e[k] for k in ('schema','eventId','payloadDigest')},headers=dh)
                    assert a.status_code == 404
    asyncio.run(scenario())


def test_label_publications_revision_acl_duplicate_revoke_and_relabel():
    async def scenario():
        async with harness() as (sessions,c):
            _, _, dh = await paired(c)
            e,a = await sent(c,dh)
            rid = a['receiptId']
            replies = await asyncio.gather(*(label(c,rid,scope=None) for _ in range(6)))
            assert sorted(r.status_code for r in replies) == [200]+[409]*5
            pub = '/api/v1/seo/distribution/v2/publications?tenant_id=4'
            assert (await c.get(pub,headers=token(8,business=True,grant=11))).json()['total'] == 0
            owner = (await c.get(pub,headers=token(business=True))).json()['items'][0]
            assert owner['source'] == 'external_report' and owner['verificationStatus'] == 'unlinked'
            assert not {'owner_user_id','deviceId','eventId','attemptId','history'} & owner.keys()
            assert (await label(c,rid,revision=1,scope=2,publishedAccount='人工账号')).status_code == 200
            # Peer needs a live site assignment even when granted the customer.
            scoped = pub+'&scope_id=2'
            assert (await c.get(scoped,headers=token(8,business=True,grant=11))).status_code == 403
            async with sessions() as s:
                s.add(SeoSiteAdvisorAssignment(id=4,tenant_id=4,site_id=2,advisor_user_id=8,active=True)); await s.commit()
            assert (await c.get(scoped,headers=token(8,business=True,grant=11))).json()['total'] == 1
            assert (await label(c,rid,headers=token(8,business=True,grant=11),revision=2)).status_code == 404
            assert (await c.post(I+'/receipts/'+rid+'/delete',json={'expectedRevision':2},headers=token())).status_code == 403
            _,b = await sent(c,dh)
            assert (await label(c,b['receiptId'])).json()['detail']['code'] == 'DUPLICATE_LINK'
            path = '/api/v1/seo/distribution/v2/receipts/'+rid+'/unlabel?tenant_id=4'
            async with sessions() as s:
                (await s.get(Grant,10)).revoked_at = svc.now(); (await s.get(Grant,10)).revoked_by=9; (await s.get(Grant,10)).revoke_reason='synthetic'; await s.commit()
            hidden = (await c.get(I+'/receipts/'+rid,headers=token())).json()
            assert hidden['assignment'] == {'hidden':True}
            assert 'tenantId' not in json.dumps(hidden['history'])
            assert (await c.post(path,json={'expectedRevision':2,'reason':'synthetic'},headers=token(business=True))).status_code in {401,403}
            assert (await c.post(path,json={'expectedRevision':2,'reason':'synthetic'},headers=token(9,admin=True))).status_code == 200
            assert (await c.get(scoped,headers=token(8,business=True,grant=11))).json()['total'] == 0
            assert (await label(c,rid,headers=token(9,admin=True),scope=3,revision=3)).status_code == 200
            assert (await c.post(I+'/device/results',json=e,headers=dh)).json() == a
    asyncio.run(scenario())


@pytest.mark.parametrize('denial',['scope','tenant','target_body','module_expired','scope_inactive','write_switch','article'])
def test_label_target_guard_fails_closed(denial, monkeypatch):
    async def scenario():
        async with harness() as (sessions,c):
            _,_,dh = await paired(c)
            _,a = await sent(c,dh)
            scope, changes, tenant = 2, {}, 4
            if denial == 'scope': scope = 3
            if denial == 'target_body': changes['targetTenant'] = 5
            if denial == 'article': changes.update(articleId=999,articleVersion=1,articleDigest='a'*64)
            if denial == 'write_switch': monkeypatch.setattr(auth.get_settings(),'advisor_scoped_content_writes_enabled',False)
            if denial in {'module_expired','scope_inactive','tenant'}:
                async with sessions() as s:
                    if denial == 'module_expired': (await s.get(TenantModule,1)).expires_at = svc.now().date()-timedelta(days=1)
                    if denial == 'scope_inactive': (await s.get(SeoSite,2)).status='paused'
                    if denial == 'tenant': (await s.get(Grant,10)).tenant_id=5
                    await s.commit()
            r = await label(c,a['receiptId'],scope=scope,**changes)
            assert r.status_code in {401,403,409}, r.text
            async with sessions() as s:
                row = await s.get(Receipt,a['receiptId'])
                assert row.revision == 0 and row.tenant_id is None
    asyncio.run(scenario())


def test_tables_absent_return_503_without_auto_create():
    async def scenario():
        async with harness(tables=False) as (_,c):
            r = await c.post(I+'/pairings',json={},headers=token())
            assert r.status_code == 503 and r.json()['detail']['code'] == 'INBOX_SCHEMA_NOT_READY'
            assert r.headers['cache-control'] == 'private, no-store'
    asyncio.run(scenario())


@pytest.mark.parametrize('header', ['Cookie','Origin','Sec-Fetch-Site','X-API-Key'])
def test_native_endpoints_reject_browser_and_api_credentials(header):
    async def scenario():
        async with harness() as (_,c):
            _,_,dh = await paired(c)
            r = await c.post(I+'/device/results',json=event(),headers={**dh,header:'synthetic'})
            assert r.status_code == 401
    asyncio.run(scenario())


def test_pending_codes_device_limits_expiry_and_search_count():
    async def scenario():
        async with harness() as (sessions,c):
            # Zero-authorized advisor still pairs and sees an empty target picker.
            async with sessions() as s:
                (await s.get(Grant,10)).revoked_at=svc.now(); (await s.get(Grant,10)).revoked_by=9; (await s.get(Grant,10)).revoke_reason='synthetic'; await s.commit()
            assert (await c.get(I+'/targets',headers=token())).json()['items'] == []
            _,d,dh = await paired(c)
            await sent(c,dh,title='find me')
            await sent(c,dh,title='other',publicUrl=None,result='risk_control')
            assert (await c.get(I+'/receipts?q=find',headers=token())).json()['total'] == 1
            counts = (await c.get(I+'/receipts/count?q=find',headers=token())).json()
            assert counts['count'] == 1 and counts['unlabeledCount'] == 2
            for _ in range(20): assert (await c.post(I+'/pairings',json={},headers=token())).status_code == 201
            assert (await c.post(I+'/pairings',json={},headers=token())).status_code == 429
            async with sessions() as s:
                for row in await s.scalars(select(Device).where(Device.state=='pending')):
                    row.pairing_expires_at=svc.now()-timedelta(seconds=1)
                await s.commit()
            assert (await c.post(I+'/pairings',json={},headers=token())).status_code == 201
            assert (await c.post(I+'/devices/'+d['deviceId']+'/revoke',json={'expectedRevision':1},headers=token())).status_code == 200
            assert (await c.post(I+'/device/results',json=event(),headers=dh)).status_code == 401
    asyncio.run(scenario())


def test_geo_project_current_assignment_picker_projection_and_revocation():
    async def scenario():
        from app.models.module_workspace import GeoProject
        from app.models.geo_optimization import GeoOptimizationBusiness
        async with harness() as (sessions,c):
            async with sessions() as s:
                for model in (GeoProject,GeoOptimizationBusiness):
                    await s.execute(CreateTable(model.__table__,include_foreign_key_constraints=[]))
                (await s.get(Role,5)).permissions={'geo.content':'edit','geo.assets':'edit'}
                s.add(TenantModule(id=2,tenant_id=4,module_code='geo',status='active'))
                s.add(GeoProject(id=5,tenant_id=4,tenant_module_id=2,name='synthetic-project',primary_domain='synthetic.invalid',
                    canonical_domain='synthetic.invalid',status='active',project_settings={
                        'geo_service_plan':{'advisor_user_id':7},'geo_business_scope':{'business_ids':[]}}))
                await s.commit()
            _,_,dh=await paired(c)
            _,a=await sent(c,dh)
            targets = await c.get(I+'/targets',headers=token())
            assert targets.status_code == 200, targets.text
            assert targets.json()['items'][0]['modules'] == ['geo']
            assert targets.json()['items'][0]['scopes'][0]['id'] == 5
            # Simulates the shared row written by GEO's separately reviewed API.
            async with sessions() as s:
                r=await s.get(Receipt,a['receiptId'])
                r.state=r.label_state='active'; r.tenant_id=4; r.module='geo'; r.scope_id=5
                await s.commit()
            detail = (await c.get(I+'/receipts/'+a['receiptId'],headers=token())).json()
            assert detail['assignment']['module']=='geo' and detail['assignment']['scopeId']==5
            async with sessions() as s:
                p=await s.get(GeoProject,5)
                p.project_settings={'geo_service_plan':{'advisor_user_id':8}}
                await s.commit()
            detail = (await c.get(I+'/receipts/'+a['receiptId'],headers=token())).json()
            assert detail['assignment']=={'hidden':True}
            assert (await c.get(I+'/targets',headers=token())).json()['items'][0]['scopes']==[]
            # Administrator can still inspect correctly, without becoming owner.
            detail = (await c.get(I+'/receipts/'+a['receiptId'],headers=token(9,admin=True))).json()
            assert detail['assignment']['scopeId']==5
    asyncio.run(scenario())


def test_article_fixed_approved_version_and_revision_invalidation():
    async def scenario():
        from app.api.seo import _content_confirmation_hash
        async with harness() as (sessions,c):
            async with sessions() as s:
                asset=SeoContentAsset(id=1000,tenant_id=4,site_id=2,title='Synthetic approved',draft='Synthetic approved body',status='ready',content_type='article',version_count=1)
                s.add(asset)
                digest=_content_confirmation_hash(asset)
                s.add(SeoContentConfirmation(id=1000,tenant_id=4,site_id=2,content_asset_id=1000,content_version=1,
                    content_hash=digest,decision='approve',actor_mode='advisor_proxy',actor_user_id=7,actor_role_name='test'))
                await s.commit()
            _,_,dh=await paired(c)
            _,a=await sent(c,dh)
            targets=await c.get(I+'/targets',headers=token())
            assert targets.status_code==200,targets.text
            articles=targets.json()['items'][0]['scopes'][0]['articles']
            assert articles and articles[0]['id']==1000
            r=await label(c,a['receiptId'],articleId=1000,articleVersion=1,articleDigest=digest)
            assert r.status_code==200,r.text
            assert r.json()['verificationStatus']=='unavailable'
            async with sessions() as s:
                asset=await s.get(SeoContentAsset,1000)
                asset.version_count=2; asset.draft='Changed'
                await s.commit()
            assert (await label(c,a['receiptId'],revision=1,articleId=1000,articleVersion=1,articleDigest=digest)).status_code==409
            async with sessions() as s:
                assert (await s.get(SeoContentAsset,1000)).status=='ready'
                assert (await s.get(Receipt,a['receiptId'])).revision==1
    asyncio.run(scenario())


@pytest.mark.parametrize('rate',['minute','hour'])
def test_persistent_rate_limits_only_new_events(rate):
    async def scenario():
        async with harness() as (sessions,c):
            _,d,dh=await paired(c)
            e,a=await sent(c,dh)
            async with sessions() as s:
                row=await s.get(Device,d['deviceId'])
                row.rate_buckets={rate:int(svc.now().timestamp())//(60 if rate=='minute' else 3600),rate+'Count':60 if rate=='minute' else 300}
                await s.commit()
            assert (await c.post(I+'/device/results',json=event(),headers=dh)).status_code==429
            assert (await c.post(I+'/device/results',json=e,headers=dh)).json()==a
    asyncio.run(scenario())


def test_cross_module_requires_unlabel_and_admin_owner_filters_do_not_leak():
    async def scenario():
        async with harness() as (sessions,c):
            _,_,dh=await paired(c)
            _,a=await sent(c,dh)
            async with sessions() as s:
                row=await s.get(Receipt,a['receiptId'])
                row.state=row.label_state='active'; row.module='geo'; row.tenant_id=4
                await s.commit()
            r=await label(c,a['receiptId'],headers=token(9,admin=True))
            assert r.status_code==409 and r.json()['detail']['code']=='CROSS_TARGET_REQUIRES_UNLABEL'
            assert (await c.get(I+'/receipts?ownerUserId=7',headers=token(8))).status_code==403
            assert (await c.get(I+'/receipts?state=active&ownerUserId=7',headers=token(9,admin=True))).json()['total']==1
            assert (await c.get(I+'/devices?ownerUserId=7',headers=token(9,admin=True))).json()['items']
    asyncio.run(scenario())


def test_ninety_day_archival_is_capacity_preserving():
    async def scenario():
        async with harness() as (sessions,c):
            _,_,dh=await paired(c)
            _,a=await sent(c,dh)
            async with sessions() as s:
                (await s.get(Receipt,a['receiptId'])).received_at=svc.now()-timedelta(days=91)
                await s.commit()
            assert (await c.get(I+'/receipts',headers=token())).json()['total']==0
            archived=(await c.get(I+'/receipts?state=archived',headers=token())).json()
            assert archived['total']==1 and archived['items'][0]['state']=='archived'
            assert (await c.get(I+'/receipts/count',headers=token())).json()['unlabeledCount']==1
    asyncio.run(scenario())


def test_geo_optional_articles_use_current_master_and_current_business_chain():
    async def scenario():
        from app.models.module_workspace import GeoProject
        from app.models.geo_optimization import GeoOptimizationBusiness, GeoOptimizationUnit
        from app.models.geo_prompt import GeoPrompt
        from app.models.geo_content import GeoContentTask, GeoArticleVersion
        async with harness() as (sessions,c):
            async with sessions() as s:
                for model in (GeoProject,GeoOptimizationBusiness,GeoOptimizationUnit,GeoPrompt,GeoContentTask,GeoArticleVersion):
                    await s.execute(CreateTable(model.__table__,include_foreign_key_constraints=[]))
                (await s.get(Role,5)).permissions={'geo.content':'edit','geo.assets':'edit'}
                s.add(TenantModule(id=2,tenant_id=4,module_code='geo',status='active'))
                s.add(GeoProject(id=5,tenant_id=4,tenant_module_id=2,name='synthetic-project',primary_domain='synthetic.invalid',
                    canonical_domain='synthetic.invalid',status='active',project_settings={
                        'geo_service_plan':{'advisor_user_id':7},'geo_business_scope':{'business_ids':[20]}}))
                s.add(GeoOptimizationBusiness(id=20,tenant_id=4,name='synthetic-business',status='active'))
                s.add(GeoOptimizationUnit(id=21,tenant_id=4,business_id=20,name='synthetic-unit',status='active'))
                s.add(GeoPrompt(id=22,tenant_id=4,unit_id=21,question='synthetic'))
                s.add(GeoContentTask(id=23,tenant_id=4,prompt_id=22,business_id=20,title='approved synthetic',review_status='approved'))
                s.add(GeoArticleVersion(id=24,task_id=23,kind='master',version_no=1,title='synthetic',body_markdown='old body'))
                s.add(GeoArticleVersion(id=25,task_id=23,kind='master',version_no=2,title='synthetic',body_markdown='current body'))
                await s.commit()
            result=await c.get(I+'/targets',headers=token())
            assert result.status_code==200,result.text
            article=result.json()['items'][0]['scopes'][0]['articles'][0]
            assert article=={'id':23,'title':'approved synthetic','version':2,'digest':svc.sha('current body')}
            assert 'current body' not in result.text and 'old body' not in result.text
            async with sessions() as s:
                (await s.get(GeoContentTask,23)).review_status='rejected'; await s.commit()
            assert (await c.get(I+'/targets',headers=token())).json()['items'][0]['scopes'][0]['articles']==[]
    asyncio.run(scenario())


def test_active_device_limit_and_expiration_release():
    async def scenario():
        async with harness() as (sessions,c):
            _,d,dh=await paired(c)
            async with sessions() as s:
                for _ in range(19):
                    s.add(Device(id=str(uuid4()),owner_user_id=7,label='synthetic',state='active',revision=1,
                        pairing_digest=svc.sha(str(uuid4())),pairing_expires_at=svc.now(),credential_digest='a'*64,
                        credential_expires_at=svc.now()+timedelta(days=1),created_at=svc.now(),rate_buckets={}))
                await s.commit()
            p=(await c.post(I+'/pairings',json={},headers=token())).json()
            req={'pairingCode':p['pairingCode'],'requestId':str(uuid4())}
            r=await c.post(I+'/device-pairings/claim',json=req)
            assert r.status_code==429 and r.json()['detail']['code']=='DEVICE_LIMIT_REACHED'
            async with sessions() as s:
                row=await s.get(Device,d['deviceId']);row.credential_expires_at=svc.now()-timedelta(seconds=1)
                await s.commit()
            assert (await c.post(I+'/device-pairings/claim',json=req)).status_code==200
    asyncio.run(scenario())
