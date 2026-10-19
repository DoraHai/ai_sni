"""Required native PostgreSQL races; absent dedicated PG is a failure, not skip."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.schema import CreateTable

from app.api import seo as api
from app.api.seo_distribution_report import router, _rates, _claim_rates, limit
from app.database import get_session
from app.models.advisor_tenant_grant import AdvisorTenantGrant
from app.models.module_workspace import TenantModule, SeoSite
from app.models.role import Role
from app.models.user import User
from app.models.seo import (SeoContentAsset, SeoContentConfirmation, SeoContentPublication,
    SeoDistributionConnection, SeoDistributionVariant, SeoPublishAttempt, SeoSiteAdvisorAssignment, SeoBacklink)
from app.security import auth
from app import seo_distribution_report as report
from app.seo_distribution_protocol import KEY, PREFIX, registry
from test_seo_workflow_postgres import database


@pytest.fixture(autouse=True)
def advisor_switches(monkeypatch):
    settings = auth.get_settings()
    monkeypatch.setattr(settings, 'advisor_multi_tenant_enabled', True)
    monkeypatch.setattr(settings, 'advisor_scoped_content_writes_enabled', True)


def advisor_bearer():
    import jwt
    exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    return 'Bearer ' + jwt.encode({'sub':'7','exp':exp,'auth_exp':exp,
        'aud':'advisor-business','scope_kind':'advisor_tenant','tid':4,'gid':10},
        auth._jwt_secret(), algorithm=auth.JWT_ALG)


@asynccontextmanager
async def fixture():
    _rates.clear()
    _claim_rates.clear()
    async with database() as sessions:
        async with sessions() as session:
            connection = await session.connection()
            for model in (AdvisorTenantGrant, SeoDistributionConnection, SeoDistributionVariant, SeoBacklink):
                await connection.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
            admin = User(id=9, username='synthetic-admin', password_hash='unused', role_id=9, is_active=True)
            session.add_all([Role(id=9, name='管理员', is_system=True,
                permissions={'settings.accounts':'edit','seo.content':'edit','seo.site':'edit'}), admin])
            (await session.get(User, 7)).tenant_id = 4
            session.add(AdvisorTenantGrant(id=10, user_id=7, tenant_id=4, granted_by=9, grant_source='admin'))
            for cid, sid in ((40, 2), (41, 3)):
                session.add(SeoDistributionConnection(id=cid, tenant_id=4, platform_code='wechat_browser',
                    name=f'synthetic-connection-{cid}', enabled=True, config={'advisor_site_id': sid}, mode='manual'))
            session.add(SeoSite(id=3, tenant_id=4, tenant_module_id=1, name='Unassigned synthetic site',
                domain='other.test', canonical_domain='other.test', status='active'))
            asset = SeoContentAsset(id=1000, tenant_id=4, site_id=2, title='Synthetic title',
                draft='<p>Approved synthetic article containing enough uniquely identifiable text.</p>',
                content_type='article', status='ready', version_count=1)
            session.add(asset)
            payload_hash = api._content_confirmation_hash(asset)
            session.add(SeoContentConfirmation(id=1000, tenant_id=4, site_id=2, content_asset_id=1000,
                content_version=1, content_hash=payload_hash, decision='approve', actor_mode='advisor_proxy',
                actor_user_id=7, actor_role_name='test'))
            session.add(SeoContentPublication(id=1001, tenant_id=4, content_asset_id=1000,
                connection_id=40, platform_code='wechat_browser', platform_name='Synthetic Wechat',
                status='manual_required', source_version=1, publish_mode='manual'))
            await session.commit()
            admin_bearer = 'Bearer ' + auth.issue_token(admin)
        app = FastAPI()
        app.include_router(router)
        async def local_session():
            async with sessions() as session:
                yield session
        app.dependency_overrides[get_session] = local_session
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://synthetic.test') as client:
            yield sessions, client, admin_bearer, payload_hash


def management_headers(bearer):
    return {'Authorization': bearer}


SCOPE = '?tenant_id=4&site_id=2'


async def new_pair(client, bearer, revision, scope=SCOPE):
    return await client.post(PREFIX+'/device-pairings'+scope,
        headers=management_headers(bearer), json={'label':'Synthetic team computer',
        'platform':'wechat-article','account_id':'seo-connection-40','expected_revision':revision})


async def claim_code(client, code):
    return await client.post(PREFIX+'/device-pairings/claim',
        json={'pairing_code':code,'request_id':str(uuid4())})


async def unbound_pair(client, bearer, revision=0, *, scope=SCOPE, explicit_null=False):
    body = {'label':'Synthetic unbound computer','platform':'wechat-article','expected_revision':revision}
    if explicit_null:
        body['account_id'] = None
    return await client.post(PREFIX+'/device-pairings'+scope, headers=management_headers(bearer), json=body)


@pytest.mark.parametrize('explicit_null', [False, True])
def test_unbound_pairing_builds_and_reuses_bound_placeholder_with_audit(explicit_null):
    async def scenario():
        async with fixture() as (sessions,client,admin,_):
            advisor = advisor_bearer()
            response = await unbound_pair(client,advisor,explicit_null=explicit_null)
            assert response.status_code == 201, response.status_code
            assert (await unbound_pair(client,advisor,1)).status_code == 201
            async with sessions() as session:
                table = SeoDistributionConnection.__table__
                rows = (await session.execute(select(table.c.id,table.c.name,table.c.mode,table.c.enabled,table.c.has_credentials,table.c.config)
                    .where(table.c.config['duohaotong_placeholder'].as_integer() == 1))).mappings().all()
                assert len(rows) == 1
                row = rows[0]
                assert row['enabled'] and not row['has_credentials']
                assert row['mode'] == 'assisted'
                assert row['config'] == {'advisor_site_id':2,'duohaotong_placeholder':1}
                assert row['name'] == '多号通公众号（发布时上报）'
                state = registry((await session.get(TenantModule,1)).module_settings)
                assert not state['enabled'] and not state['scopes']
                assert {p['account_id'] for p in state['pairings'].values()} == {f"seo-connection-{row['id']}"}
                created = [a for a in state['audit'] if a['action'] == 'placeholder_connection_created_for_pairing']
                assert len(created) == 1 and created[0]['actor'] == 7
                assert (created[0]['tenant_id'],created[0]['site_id'],created[0]['connection_id']) == (4,2,row['id'])
            claim = (await claim_code(client,response.json()['pairing_code'])).json()
            assert set(claim) == {'schema','pairing_id','claimed_at','device','bindings_configured','automatic_submit'}
            device = claim['device']
            profile = (await client.get(PREFIX+'/device/profile',headers=management_headers('Bearer '+device['credential']))).json()
            assert set(profile) == {'schema','device_id','customer_name','scope_name','account_name','label'}
            assert profile['account_name'] == '多号通公众号（发布时上报）'
            bindings = await client.post(PREFIX+'/device/bindings',headers=device_headers(device,1),json={'device_id':device['id']})
            assert bindings.status_code == 200
            assert set(bindings.json()) == {'schema','device_id','as_of','automatic_submit','items'}
            assert bindings.json()['items'][0]['account_id'] == f"seo-connection-{row['id']}"
    asyncio.run(scenario())


def test_placeholder_can_prepare_official_account_specific_variant():
    async def scenario():
        async with fixture() as (sessions,client,admin,_):
            assert (await unbound_pair(client,admin)).status_code == 201
            async with sessions() as session:
                cid = await session.scalar(select(SeoDistributionConnection.id).where(
                    SeoDistributionConnection.config['duohaotong_placeholder'].as_integer() == 1))
                ctx = await auth._build_context(await session.get(User,9),session)
                result = await api.save_distribution_variant(api.DistributionVariantSaveRequest(
                    tenant_id=4,site_id=2,content_id=1000,connection_id=cid,source_version=1,
                    title='Synthetic official account title',content='<p>Synthetic account specific article.</p>'),session,ctx)
                assert result['connection_id'] == cid and result['platform_code'] == 'wechat_browser'
                assert result['status'] == 'draft'
    asyncio.run(scenario())


def test_concurrent_unbound_pairings_do_not_duplicate_placeholder_and_sites_are_separate():
    async def scenario():
        async with fixture() as (sessions,client,admin,_):
            responses = await asyncio.gather(*(unbound_pair(client,admin) for _ in range(8)))
            assert sum(r.status_code == 201 for r in responses) == 1
            assert sum(r.status_code == 409 for r in responses) == 7
            assert (await unbound_pair(client,admin,1)).status_code == 201
            assert (await unbound_pair(client,admin,2,scope='?tenant_id=4&site_id=3')).status_code == 201
            async with sessions() as session:
                table = SeoDistributionConnection.__table__
                rows = (await session.execute(select(table.c.name,table.c.config)
                    .where(table.c.config['duohaotong_placeholder'].as_integer() == 1))).mappings().all()
                assert len(rows) == 2 and len({r['name'] for r in rows}) == 2
                assert {r['config']['advisor_site_id'] for r in rows} == {2,3}
    asyncio.run(scenario())


def test_unbound_advisor_denials_create_nothing_and_disabled_placeholder_is_not_reopened():
    async def scenario():
        from sqlalchemy import update
        async with fixture() as (sessions,client,admin,_):
            for scope in ('?tenant_id=4&site_id=3','?tenant_id=6&site_id=2'):
                assert (await unbound_pair(client,advisor_bearer(),scope=scope)).status_code == 403
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(SeoDistributionConnection)) == 2
            assert (await unbound_pair(client,admin)).status_code == 201
            async with sessions() as session:
                await session.execute(update(SeoDistributionConnection).where(
                    SeoDistributionConnection.config['duohaotong_placeholder'].as_integer() == 1).values(enabled=False))
                await session.commit()
            response = await unbound_pair(client,admin,1)
            assert response.status_code == 409 and response.json()['detail']['code'] == 'PLACEHOLDER_DISABLED'
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(SeoDistributionConnection)) == 3
                assert len(registry((await session.get(TenantModule,1)).module_settings)['pairings']) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('with_account', [False, True])
def test_placeholder_dispatch_and_reported_account_success_replay_and_native_copy(with_account, monkeypatch):
    async def scenario():
        from app import seo_distribution_verification as verification
        monkeypatch.setattr(verification,'recover_report_verification',AsyncMock())
        async with fixture() as (sessions,client,admin,payload_hash):
            pairing = await unbound_pair(client,advisor_bearer())
            assert pairing.status_code == 201
            device = (await claim_code(client,pairing.json()['pairing_code'])).json()['device']
            async with sessions() as session:
                cid = await session.scalar(select(SeoDistributionConnection.id).where(
                    SeoDistributionConnection.config['duohaotong_placeholder'].as_integer() == 1))
                (await session.get(SeoContentPublication,1001)).connection_id = cid
                await session.commit()
            response = await client.put(PREFIX+'/settings'+SCOPE,headers=management_headers(admin),json={
                'enabled':True,'scope_enabled':True,'expected_revision':1,'expected_scope_revision':0})
            assert response.status_code == 200
            response = await client.post(PREFIX+'/tasks'+SCOPE,headers=management_headers(advisor_bearer()),json={
                'publication_id':1001,'source_version':1,'payload_hash':payload_hash,'device_id':device['id'],'request_id':str(uuid4())})
            assert response.status_code == 201, response.status_code
            task_id = response.json()['taskId']
            envelope = await client.post(PREFIX+'/device/exchange',headers=device_headers(device,1),json={
                'contractVersion':1,'deviceId':device['id'],'receipts':[]})
            task = envelope.json()['tasks'][0]
            event = event_for(device,task)
            if with_account:
                event['reportedAccount'] = {'name':'  合成\u200b公众号　 测试😀 '}
            body = {'contractVersion':1,'deviceId':device['id'],'receipts':[event]}
            response = await client.post(PREFIX+'/device/exchange',headers=device_headers(device,2),json=body)
            assert response.status_code == 200, response.status_code
            assert set(response.json()) == {'contractVersion','deviceAuthorized','receiptAcks','pausedTaskIds','binding','paused','grants','tasks'}
            assert len(response.json()['receiptAcks'][0]) == 6
            replay = await client.post(PREFIX+'/device/exchange',headers=device_headers(device,3),json=body)
            assert replay.status_code == 200 and replay.json()['receiptAcks'] == response.json()['receiptAcks']
            detail = (await client.get(PREFIX+'/tasks/'+task_id+SCOPE,headers=management_headers(admin))).json()
            assert detail['reportedAccount'] == ({'name':'合成公众号 测试😀'} if with_account else None)
            verification = await client.get(PREFIX+'/device/tasks/'+task_id+'/verification',
                headers=management_headers('Bearer '+device['credential']))
            assert verification.status_code == 200
            assert set(verification.json()) == {'taskId','nativePublicationId','deviceId','reportedOutcome',
                'delivery','last_code','verification','publicationVerified'}
            async with sessions() as session:
                assert (await session.get(SeoContentPublication,1001)).status == 'published'
                assert await session.scalar(select(func.count()).select_from(SeoPublishAttempt)) == 1
                summary = await session.scalar(select(SeoPublishAttempt.response_summary))
                assert summary.get('reportedAccount') == detail['reportedAccount']
                state = registry((await session.get(TenantModule,1)).module_settings)
                assert state['tasks'][task_id]['target']['accountId'] == f'seo-connection-{cid}'
            changed = {**event,'reportedAccount':{'name':'另一合成号'}}
            conflict = await client.post(PREFIX+'/device/exchange',headers=device_headers(device,4),json={**body,'receipts':[changed]})
            assert conflict.status_code == 409 and conflict.json()['detail']['code'] == 'IDEMPOTENCY_CONFLICT'
    asyncio.run(scenario())


@pytest.mark.parametrize('account', [None, {}, {'name':''}, {'name':'x'*61}, {'name':1}, {'name':'合成','extra':True}])
def test_invalid_reported_account_is_atomic(account):
    async def scenario():
        async with fixture() as (sessions,client,admin,payload_hash):
            device,task,task_id = await ready(client,admin,payload_hash)
            event = event_for(device,task,reportedAccount=account)
            response = await client.post(PREFIX+'/device/exchange',headers=device_headers(device,2),json={
                'contractVersion':1,'deviceId':device['id'],'receipts':[event]})
            assert response.status_code == 422 and response.json()['detail']['code'] == 'INVALID_REPORTED_ACCOUNT'
            async with sessions() as session:
                assert (await session.get(SeoContentPublication,1001)).status == 'manual_required'
                assert await session.scalar(select(func.count()).select_from(SeoPublishAttempt)) == 0
                assert not registry((await session.get(TenantModule,1)).module_settings)['tasks'][task_id]['streams']['receipt']['events']
    asyncio.run(scenario())


def test_twenty_pending_codes_and_twenty_active_devices_are_tenant_wide():
    async def scenario():
        async with fixture() as (sessions,client,admin,_):
            codes = []
            for revision in range(20):
                response = await new_pair(client,admin,revision)
                assert response.status_code == 201
                codes.append(response.json()['pairing_code'])
            assert (await new_pair(client,admin,20)).status_code == 429
            # Twenty simultaneous claims serialize without exceeding capacity.
            results = await asyncio.gather(*(claim_code(client,code) for code in codes))
            assert all(r.status_code == 200 for r in results)
            assert (await new_pair(client,admin,20)).status_code == 429
            async with sessions() as session:
                state = registry((await session.get(TenantModule,1)).module_settings)
                assert len(state['devices']) == 20
                assert all(p['consumed'] for p in state['pairings'].values())
                assert all(not p.get('claim_failures') for p in state['pairings'].values())
    asyncio.run(scenario())


@pytest.mark.parametrize('label', ['', '   ', '\t', 'a'*81, 'team\x00', '\u200b'])
def test_device_note_is_required_and_safe_on_server(label):
    async def scenario():
        async with fixture() as (sessions,client,admin,_):
            response = await client.post(PREFIX+'/device-pairings'+SCOPE,
                headers=management_headers(admin),json={'label':label,'platform':'wechat-article',
                'account_id':'seo-connection-40','expected_revision':0})
            assert response.status_code == 422
            async with sessions() as session:
                assert not registry((await session.get(TenantModule,1)).module_settings,initialize=True)['pairings']
    asyncio.run(scenario())


def test_known_code_failure_limit_survives_new_worker_and_time_window(monkeypatch):
    async def scenario():
        async with fixture() as (sessions,client,admin,_):
            pairing = await pair(client,admin)
            assert (await claim_code(client,pairing['pairing_code'])).status_code == 200
            for _ in range(10):
                assert (await claim_code(client,pairing['pairing_code'])).status_code == 409
            # A new ASGI application and empty process-local caches simulate a
            # restart; only JSONB committed in distinct sessions can block it.
            _claim_rates.clear(); _rates.clear()
            restarted = FastAPI(); restarted.include_router(router)
            async def local_session():
                async with sessions() as session:
                    yield session
            restarted.dependency_overrides[get_session] = local_session
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted),base_url='http://synthetic.test') as fresh:
                response = await claim_code(fresh,pairing['pairing_code'])
                assert response.status_code == 429 and response.headers['retry-after'] == '60'
                async with sessions() as session:
                    state = registry((await session.get(TenantModule,1)).module_settings)
                    assert len(state['pairings'][report.sha(pairing['pairing_code'])]['claim_failures']) == 10
                tick = report.now_ms()
                monkeypatch.setattr(report,'now_ms',lambda:tick+60001)
                assert (await claim_code(fresh,pairing['pairing_code'])).status_code == 409
    asyncio.run(scenario())


def test_same_source_can_claim_many_customers_without_success_budget():
    async def scenario():
        from app.models.tenant import Tenant
        async with fixture() as (sessions,client,admin,_):
            for index in range(35):
                tid,sid,cid = 100+index,200+index,300+index
                async with sessions() as session:
                    session.add(Tenant(id=tid,name='Synthetic customer'))
                    session.add(TenantModule(id=100+index,tenant_id=tid,module_code='seo',status='active'))
                    session.add(SeoSite(id=sid,tenant_id=tid,tenant_module_id=100+index,
                        name='Synthetic site',domain=f'customer-{index}.test',canonical_domain=f'customer-{index}.test',status='active'))
                    session.add(SeoDistributionConnection(id=cid,tenant_id=tid,platform_code='wechat_browser',
                        name='Synthetic account',enabled=True,config={'advisor_site_id':sid},mode='manual'))
                    await session.commit()
                response = await client.post(PREFIX+f'/device-pairings?tenant_id={tid}&site_id={sid}',
                    headers=management_headers(admin),json={'label':'Team computer','platform':'wechat-article',
                    'account_id':f'seo-connection-{cid}','expected_revision':0})
                assert response.status_code == 201
                assert (await claim_code(client,response.json()['pairing_code'])).status_code == 200
            assert not _claim_rates
    asyncio.run(scenario())


def test_profile_is_own_safe_metadata_without_changing_old_wire_shapes():
    async def scenario():
        from app.models.tenant import Tenant
        async with fixture() as (sessions,client,admin,_):
            first = (await claim_code(client,(await pair(client,admin))['pairing_code'])).json()
            second = (await claim_code(client,(await new_pair(client,admin,1)).json()['pairing_code'])).json()
            assert set(first) == {'schema','pairing_id','claimed_at','device','bindings_configured','automatic_submit'}
            assert set(first['device']) == {'id','label','active','credential','credential_once'}
            async with sessions() as session:
                (await session.get(Tenant,4)).name = '客户\u200b\n  名称'
                (await session.get(SeoSite,2)).name = '站'*120
                (await session.get(SeoDistributionConnection,40)).name = '  公众号\x01测试  '
                await session.commit()
            device = first['device']; headers = {'Authorization':'Bearer '+device['credential']}
            response = await client.get(PREFIX+'/device/profile',headers=headers)
            assert response.status_code == 200 and response.headers['cache-control'] == 'private, no-store'
            value = response.json()
            assert set(value) == {'schema','device_id','customer_name','scope_name','account_name','label'}
            assert value == {'schema':1,'device_id':device['id'],'customer_name':'客户 名称',
                'scope_name':'站'*120,'account_name':'公众号测试','label':'Synthetic computer'}
            assert value['device_id'] != second['device']['id']
            for query in ('?device_id='+second['device']['id'],'?tenant_id=6','?site_id=3'):
                assert (await client.get(PREFIX+'/device/profile'+query,headers=headers)).status_code == 422
            assert (await client.get(PREFIX+'/device/profile')).status_code == 401
            assert (await client.get(PREFIX+'/device/profile',headers={'Authorization':'Bearer '+'A'*64})).status_code == 401
            for key in ('Cookie','Origin','Sec-Fetch-Site'):
                assert (await client.get(PREFIX+'/device/profile',headers={**headers,key:'synthetic'})).status_code == 403
            # GET did not consume a transport sequence. Frozen 0.3.4 POST
            # still works with seq=1 and exactly the original five keys.
            response = await client.post(PREFIX+'/device/bindings',headers=device_headers(device,1),json={'device_id':device['id']})
            assert response.status_code == 200
            assert set(response.json()) == {'schema','device_id','as_of','automatic_submit','items'}
            revoked = await client.post(PREFIX+f"/devices/{device['id']}/revoke"+SCOPE,
                headers=management_headers(admin),json={'expected_revision':2})
            assert revoked.status_code == 200
            assert (await client.get(PREFIX+'/device/profile',headers=headers)).status_code == 403
    asyncio.run(scenario())


async def pair(client, bearer):
    response = await client.post(PREFIX + '/device-pairings' + SCOPE,
        headers=management_headers(bearer), json={'label':'Synthetic computer','platform':'wechat-article',
            'account_id':'seo-connection-40','expected_revision':0})
    assert response.status_code == 201, response.status_code
    return response.json()


async def ready(client, bearer, payload_hash, *, actor_bearer=None):
    pairing = await pair(client, bearer)
    response = await client.post(PREFIX + '/device-pairings/claim',
        json={'pairing_code':pairing['pairing_code'],'request_id':str(uuid4())})
    assert response.status_code == 200, response.status_code
    claim = response.json()
    device = claim['device']
    response = await client.put(PREFIX + '/settings' + SCOPE, headers=management_headers(bearer),
        json={'enabled':True,'scope_enabled':True,'expected_revision':1,'expected_scope_revision':0})
    assert response.status_code == 200, response.status_code
    request = {'publication_id':1001,'source_version':1,'payload_hash':payload_hash,
               'device_id':device['id'],'request_id':str(uuid4())}
    response = await client.post(PREFIX + '/tasks' + SCOPE,
        headers=management_headers(actor_bearer or bearer), json=request)
    assert response.status_code == 201, response.status_code
    task_id = response.json()['taskId']
    response = await client.post(PREFIX + '/device/exchange', headers=device_headers(device, 1),
        json={'contractVersion':1,'deviceId':device['id'],'receipts':[]})
    assert response.status_code == 200, response.status_code
    envelope = response.json()
    assert len(envelope['tasks']) == 1 and len(envelope['grants']) == 2
    return device, envelope['tasks'][0], task_id


def device_headers(device, seq, at=None):
    return {'Authorization':'Bearer '+device['credential'], 'X-Distribution-Request-Seq':str(seq),
            'X-Distribution-Sent-At':str(at or report.now_ms())}


def event_for(device, task, **updates):
    result = {k:task[k] for k in ('customerId','projectId','deviceId','accountId','platform','leaseId','contentDigest')}
    result.update(receiptId=str(uuid4()), sequence=3, contractVersion=1, taskId=task['id'],
        contentVersion=task['content']['version'], status='succeeded', code='HUMAN_PUBLISHED',
        at=report.now_ms(), evidence='human-reported', publicUrl='https://mp.weixin.qq.com/s/synthetic_article')
    result.update(updates)
    return result


def test_claim_competition_issues_exactly_one_credential_and_stores_only_hash():
    async def scenario():
        async with fixture() as (sessions, client, bearer, payload_hash):
            pairing = await pair(client, bearer)
            body = {'pairing_code':pairing['pairing_code'],'request_id':str(uuid4())}
            responses = await asyncio.gather(*(client.post(PREFIX+'/device-pairings/claim', json=body) for _ in range(8)))
            assert sum(r.status_code == 200 for r in responses) == 1
            assert sum(r.status_code == 409 for r in responses) == 7
            winner = next(r.json() for r in responses if r.status_code == 200)
            assert re.fullmatch(r'[A-Za-z0-9_-]{64}', winner['device']['credential'])
            async with sessions() as session:
                module = await session.get(TenantModule, 1)
                encoded = json.dumps(module.module_settings)
                assert pairing['pairing_code'] not in encoded
                assert winner['device']['credential'] not in encoded
                assert len(registry(module.module_settings)['devices']) == 1
    asyncio.run(scenario())


def test_success_double_race_and_ack_loss_have_one_native_effect(monkeypatch):
    async def scenario():
        from app import seo_distribution_verification as verification
        monkeypatch.setattr(verification, 'recover_report_verification', AsyncMock())
        async with fixture() as (sessions, client, bearer, payload_hash):
            device, task, task_id = await ready(client, bearer, payload_hash)
            event = event_for(device, task)
            body = {'contractVersion':1,'deviceId':device['id'],'receipts':[event]}
            headers = device_headers(device, 2)
            responses = await asyncio.gather(*(client.post(PREFIX+'/device/exchange', headers=headers, json=body) for _ in range(8)))
            assert [r.status_code for r in responses] == [200] * 8
            acks = [r.json()['receiptAcks'] for r in responses]
            assert all(a == acks[0] for a in acks)
            resend = await client.post(PREFIX+'/device/exchange', headers=device_headers(device, 5), json=body)
            assert resend.status_code == 200
            assert resend.json()['receiptAcks'] == acks[0]
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(SeoPublishAttempt)) == 1
                row = await session.get(SeoContentPublication, 1001)
                assert row.status == 'published' and row.page_url == event['publicUrl']
                state = registry((await session.get(TenantModule, 1)).module_settings)
                assert len(state['tasks'][task_id]['streams']['receipt']['events']) == 1
                assert state['tasks'][task_id]['verification']['state'] == 'pending'
    asyncio.run(scenario())


@pytest.mark.parametrize('mutation', ['credential','device','tenant','project','task','lease','digest','version','url','closed','grant'])
def test_denials_are_atomic_and_never_ack(mutation, monkeypatch):
    async def scenario():
        from app import seo_distribution_verification as verification
        monkeypatch.setattr(verification, 'recover_report_verification', AsyncMock())
        async with fixture() as (sessions, client, bearer, payload_hash):
            device, task, task_id = await ready(client, bearer, payload_hash)
            event = event_for(device, task)
            if mutation == 'credential': device = {**device, 'credential':device['credential'][:-1] + ('x' if device['credential'][-1]!='x' else 'y')}
            for kind, key, value in [('device','deviceId','other-device'),('tenant','customerId','202'),
                ('project','projectId','seo-3'),('task','taskId','unissued-task'),('lease','leaseId','other-lease'),
                ('digest','contentDigest','b'*64),('version','contentVersion','v99'),('url','publicUrl','https://127.0.0.1/s/evil')]:
                if mutation == kind: event[key] = value
            async with sessions() as session:
                if mutation == 'closed':
                    module = await report.locked_module(session, 4)
                    state = registry(module.module_settings)
                    state['enabled'] = False
                    report.store(module, state)
                if mutation == 'grant':
                    (await session.get(User, 9)).is_active = False
                await session.commit()
            response = await client.post(PREFIX+'/device/exchange', headers=device_headers(device, 2),
                json={'contractVersion':1,'deviceId':device['id'],'receipts':[event]})
            assert response.status_code in {401,403,404,409,422}, response.status_code
            assert 'receiptAcks' not in response.json()
            async with sessions() as session:
                assert (await session.get(SeoContentPublication,1001)).status == 'manual_required'
                assert await session.scalar(select(func.count()).select_from(SeoPublishAttempt)) == 0
                state = registry((await session.get(TenantModule,1)).module_settings)
                assert not state['tasks'][task_id]['streams']['receipt']['events']
                assert state['devices'][device['id']]['transport_seq'] == 1
    asyncio.run(scenario())


def test_replay_fingerprint_covers_body_and_timestamp(monkeypatch):
    async def scenario():
        async with fixture() as (sessions, client, bearer, payload_hash):
            device, task, _ = await ready(client, bearer, payload_hash)
            event = event_for(device, task, code='HUMAN_REQUIRED', status='awaiting-human', evidence='none', publicUrl=None)
            body = {'contractVersion':1,'deviceId':device['id'],'receipts':[event]}
            headers = device_headers(device, 2)
            first = await client.post(PREFIX+'/device/exchange', headers=headers, json=body)
            assert first.status_code == 200
            changed = {**body, 'receipts':[]}
            denied = await client.post(PREFIX+'/device/exchange', headers=headers, json=changed)
            assert denied.status_code == 409 and denied.json()['detail']['code'] == 'REPLAY_REJECTED'
            denied = await client.post(PREFIX+'/device/exchange', headers=device_headers(device,2,int(headers['X-Distribution-Sent-At'])+1), json=body)
            assert denied.status_code == 409
            replay = await client.post(PREFIX+'/device/exchange', headers=headers, json=body)
            assert replay.status_code == 200 and replay.json()['receiptAcks'] == first.json()['receiptAcks']
            assert len(replay.json()['grants']) == 2 and not replay.json()['tasks']
    asyncio.run(scenario())


def test_observations_never_publish_and_batch_failure_rolls_back(monkeypatch):
    async def scenario():
        async with fixture() as (sessions, client, bearer, payload_hash):
            device, task, task_id = await ready(client, bearer, payload_hash)
            event = event_for(device, task, code='RISK_CONTROL', status='awaiting-human', evidence='none', publicUrl=None)
            observation = {k:v for k,v in event.items() if k not in {'deviceId','contractVersion','receiptId'}}
            observation['observationId'] = str(uuid4())
            response = await client.post(PREFIX+'/device/observations', headers=device_headers(device,2),
                json={'observationVersion':1,'deviceId':device['id'],'items':[observation]})
            assert response.status_code == 200
            assert len(response.json()['acks'][0]) == 7
            first = event_for(device, task, code='HUMAN_REQUIRED', status='awaiting-human', evidence='none', publicUrl=None)
            bad = event_for(device, task, sequence=4, customerId='202')
            denied = await client.post(PREFIX+'/device/exchange', headers=device_headers(device,3),
                json={'contractVersion':1,'deviceId':device['id'],'receipts':[first,bad]})
            assert denied.status_code == 403
            async with sessions() as session:
                assert (await session.get(SeoContentPublication,1001)).status == 'manual_required'
                state = registry((await session.get(TenantModule,1)).module_settings)
                assert not state['tasks'][task_id]['streams']['receipt']['events']
                assert len(state['tasks'][task_id]['streams']['observation']['events']) == 1
    asyncio.run(scenario())


def test_concurrent_quota_and_registry_preserve_unknown_json_namespaces():
    async def scenario():
        from app.seo_usage_limits import charge_seo_usage
        async with fixture() as (sessions, client, bearer, payload_hash):
            async with sessions() as stale:
                old = await stale.get(TenantModule,1)
                assert old.module_settings is None
                async def charge():
                    async with sessions() as session:
                        await charge_seo_usage(session,4,'synthetic_usage',1,100)
                await asyncio.gather(*(charge() for _ in range(6)))
                module = await report.locked_module(stale,4)
                state = registry(module.module_settings,initialize=True)
                state['scopes']['2'] = {'enabled':True,'revision':1}
                report.store(module,state)
                await stale.commit()
            async with sessions() as session:
                settings = (await session.get(TenantModule,1)).module_settings
                assert settings['seo_daily_usage']['synthetic_usage'] == 6
                assert settings[KEY]['scopes']['2']['enabled'] is True
    asyncio.run(scenario())


def test_failures_never_become_verified():
    from app.seo_distribution_verification import verification_result
    assert verification_result({'state':'not_observed','reason':'text_not_found'},'succeeded')['state'] == 'failed'
    assert verification_result({'state':'content_observed','reason':'matching_answer_text'},'capture_disabled')['state'] == 'unavailable'
    assert verification_result({'state':'unavailable','reason':'blocked'},'succeeded')['state'] == 'unavailable'


def test_advisor_operations_require_live_tenant_grant_and_site_assignment():
    async def scenario():
        async with fixture() as (sessions, client, admin, payload_hash):
            bearer = advisor_bearer()
            pairing = await pair(client, bearer)
            for scope in ('?tenant_id=4&site_id=3','?tenant_id=6&site_id=2'):
                response = await client.get(PREFIX+'/settings'+scope, headers=management_headers(bearer))
                assert response.status_code == 403
            device_response = await client.post(PREFIX+'/device-pairings/claim', json={
                'pairing_code':pairing['pairing_code'],'request_id':str(uuid4())})
            assert device_response.status_code == 200
            device = device_response.json()['device']
            response = await client.post(PREFIX+f"/devices/{device['id']}/revoke"+SCOPE,
                headers=management_headers(bearer), json={'expected_revision':1})
            assert response.status_code == 200
            async with sessions() as session:
                assert registry((await session.get(TenantModule,1)).module_settings)['devices'][device['id']]['revoked']
    asyncio.run(scenario())


@pytest.mark.parametrize('revocation',['grant','assignment','permission'])
def test_inflight_advisor_authorization_revocation_prevents_native_write(revocation, monkeypatch):
    async def scenario():
        from app import seo_distribution_verification as verification
        monkeypatch.setattr(verification,'recover_report_verification',AsyncMock())
        async with fixture() as (sessions,client,admin,payload_hash):
            device, task, task_id = await ready(client,admin,payload_hash,actor_bearer=advisor_bearer())
            async with sessions() as revoker:
                if revocation == 'grant':
                    row = await revoker.get(AdvisorTenantGrant,10,with_for_update=True)
                    row.revoked_at = datetime.now(timezone.utc)
                    row.revoked_by, row.revoke_reason = 9, 'manual'
                elif revocation == 'assignment':
                    row = await revoker.get(SeoSiteAdvisorAssignment,3,with_for_update=True)
                    row.active = False
                else:
                    row = await revoker.get(Role,5,with_for_update=True)
                    row.permissions = {'seo.site':'edit','seo.content':'view'}
                await revoker.flush()
                pending = asyncio.create_task(client.post(PREFIX+'/device/exchange',
                    headers=device_headers(device,2),json={'contractVersion':1,'deviceId':device['id'],'receipts':[event_for(device,task)]}))
                await asyncio.sleep(0.05)
                await revoker.commit()
                result = await asyncio.wait_for(pending,timeout=10)
                assert result.status_code in {401,403}, result.status_code
            async with sessions() as session:
                assert (await session.get(SeoContentPublication,1001)).status == 'manual_required'
                assert not registry((await session.get(TenantModule,1)).module_settings)['tasks'][task_id]['streams']['receipt']['events']
    asyncio.run(scenario())


def test_cookie_origin_forged_tokens_and_closed_duplicate_never_ack(monkeypatch,caplog):
    async def scenario():
        from app import seo_distribution_verification as verification
        monkeypatch.setattr(verification,'recover_report_verification',AsyncMock())
        async with fixture() as (sessions,client,admin,payload_hash):
            device,task,_ = await ready(client,admin,payload_hash)
            receipt = event_for(device,task)
            body = {'contractVersion':1,'deviceId':device['id'],'receipts':[receipt]}
            for extra in ({'Origin':'https://evil.test'},{'Cookie':'synthetic=1'},{'Sec-Fetch-Mode':'cors'}):
                response = await client.post(PREFIX+'/device/exchange',headers={**device_headers(device,2),**extra},json=body)
                assert response.status_code == 403
            invalid = await client.post(PREFIX+'/device/exchange',headers={'Authorization':admin},json=body)
            assert invalid.status_code == 401
            first = await client.post(PREFIX+'/device/exchange',headers=device_headers(device,2),json=body)
            assert first.status_code == 200
            disabled = await client.put(PREFIX+'/settings'+SCOPE,headers=management_headers(admin),
                json={'enabled':False,'scope_enabled':False,'expected_revision':2,'expected_scope_revision':1})
            assert disabled.status_code == 200
            duplicate = await client.post(PREFIX+'/device/exchange',headers=device_headers(device,3),json=body)
            assert duplicate.status_code == 403 and 'receiptAcks' not in duplicate.json()
            assert device['credential'] not in caplog.text
            assert admin[7:] not in caplog.text
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(SeoPublishAttempt)) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('body', ['<p>Wrong article with the same title.</p>',
    '<p>Approved synthetic article containing enough uniquely identifiable text.</p>'])
def test_verification_recovers_after_ack_and_keeps_capture_gap(body,monkeypatch):
    async def scenario():
        from app import seo_distribution_verification as verification
        from app import seo_backlinks
        monkeypatch.setattr(verification,'recover_report_verification',AsyncMock())
        async with fixture() as (sessions,client,admin,payload_hash):
            device,task,task_id = await ready(client,admin,payload_hash)
            event = event_for(device,task)
            response = await client.post(PREFIX+'/device/exchange',headers=device_headers(device,2),
                json={'contractVersion':1,'deviceId':device['id'],'receipts':[event]})
            assert response.status_code == 200
            monkeypatch.setattr(verification,'async_session_factory',sessions)
            monkeypatch.setattr(api,'_queue_published_page_verification',AsyncMock(return_value={
                'state':'not_queued','capture_id':None,'reason':'capture_disabled'}))
            monkeypatch.setattr(seo_backlinks,'fetch_backlink_page',AsyncMock(return_value=SimpleNamespace(
                body=body,final_url=event['publicUrl'],status_code=200,error_type=None)))
            await verification.verify_one(4,task_id)
            async with sessions() as session:
                state = registry((await session.get(TenantModule,1)).module_settings)
                result = state['tasks'][task_id]['verification']
                assert result['state'] in {'failed','unavailable'}
                assert result['capture']['state'] == 'capture_disabled'
                assert (await session.get(SeoContentPublication,1001)).status == 'published'
    asyncio.run(scenario())


def test_claim_rate_limit_one_peer_cannot_exhaust_other_tenants():
    async def scenario():
        async with fixture() as (sessions,client,admin,payload_hash):
            pairing = await pair(client,admin)
            for _ in range(30):
                response = await client.post(PREFIX+'/device-pairings/claim',json={
                    'pairing_code':uuid4().hex,'request_id':str(uuid4())})
                assert response.status_code == 409
            limited = await client.post(PREFIX+'/device-pairings/claim',json={
                'pairing_code':uuid4().hex,'request_id':str(uuid4())})
            assert limited.status_code == 429 and limited.headers['retry-after'] == '60'
            # Even after this source's failed guesses, a valid claim succeeds.
            result = await client.post(PREFIX+'/device-pairings/claim',json={
                'pairing_code':pairing['pairing_code'],'request_id':str(uuid4())})
            assert result.status_code == 200
            _claim_rates.clear()
            pairing = await client.post(PREFIX+'/device-pairings'+SCOPE,
                headers=management_headers(admin),json={'label':'Synthetic second computer',
                'platform':'wechat-article','account_id':'seo-connection-40','expected_revision':1})
            pairing = pairing.json()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client._transport.app,
                client=('198.51.100.2',50000)),base_url='http://synthetic.test') as other:
                result = await other.post(PREFIX+'/device-pairings/claim',json={
                    'pairing_code':pairing['pairing_code'],'request_id':str(uuid4())})
                assert result.status_code == 200
    asyncio.run(scenario())


@pytest.mark.parametrize('change_during_fetch',[False,True])
def test_verification_version_change_is_recorded_before_and_after_fetch(change_during_fetch,monkeypatch):
    async def scenario():
        from app import seo_distribution_verification as verification
        from app import seo_backlinks
        monkeypatch.setattr(verification,'recover_report_verification',AsyncMock())
        async with fixture() as (sessions,client,admin,payload_hash):
            device,task,task_id = await ready(client,admin,payload_hash)
            event = event_for(device,task)
            response = await client.post(PREFIX+'/device/exchange',headers=device_headers(device,2),
                json={'contractVersion':1,'deviceId':device['id'],'receipts':[event]})
            assert response.status_code == 200
            async def change():
                async with sessions() as session:
                    asset = await session.get(SeoContentAsset,1000,with_for_update=True)
                    asset.draft, asset.version_count = '<p>Changed synthetic article.</p>', 2
                    await session.commit()
            async def fetched(url):
                await change()
                return SimpleNamespace(body='<p>Approved synthetic article containing enough uniquely identifiable text.</p>',
                    final_url=url,status_code=200,error_type=None)
            monkeypatch.setattr(verification,'async_session_factory',sessions)
            monkeypatch.setattr(api,'_queue_published_page_verification',AsyncMock(return_value={
                'state':'not_queued','capture_id':None,'reason':'capture_disabled'}))
            probe = AsyncMock(side_effect=fetched)
            monkeypatch.setattr(seo_backlinks,'fetch_backlink_page',probe)
            if not change_during_fetch:
                await change()
            await verification.verify_one(4,task_id)
            async with sessions() as session:
                state = registry((await session.get(TenantModule,1)).module_settings)
                assert state['tasks'][task_id]['verification']['state'] == 'version_changed'
            assert probe.await_count == int(change_during_fetch)
    asyncio.run(scenario())


def test_native_write_flushed_then_failure_rolls_back_fact_and_ledger(monkeypatch):
    async def scenario():
        original = api.complete_manual_publication_in_transaction
        async def fail_after_native_flush(session,*args,**kwargs):
            await original(session,*args,**kwargs)
            await session.flush()
            raise HTTPException(503,{'code':'REPORT_STORAGE_UNAVAILABLE'})
        monkeypatch.setattr(api,'complete_manual_publication_in_transaction',fail_after_native_flush)
        async with fixture() as (sessions,client,admin,payload_hash):
            device,task,task_id = await ready(client,admin,payload_hash)
            response = await client.post(PREFIX+'/device/exchange',headers=device_headers(device,2),
                json={'contractVersion':1,'deviceId':device['id'],'receipts':[event_for(device,task)]})
            assert response.status_code == 503 and 'receiptAcks' not in response.json()
            async with sessions() as session:
                assert (await session.get(SeoContentPublication,1001)).status == 'manual_required'
                assert (await session.get(SeoContentAsset,1000)).status == 'ready'
                assert await session.scalar(select(func.count()).select_from(SeoPublishAttempt)) == 0
                state = registry((await session.get(TenantModule,1)).module_settings)
                assert not state['tasks'][task_id]['streams']['receipt']['events']
                assert state['devices'][device['id']]['transport_seq'] == 1
    asyncio.run(scenario())


def test_old_manual_completion_and_device_report_share_native_serialization(monkeypatch):
    async def scenario():
        from app import seo_distribution_verification as verification
        monkeypatch.setattr(verification,'recover_report_verification',AsyncMock())
        monkeypatch.setattr(api,'_queue_published_page_verification',AsyncMock(return_value={'state':'not_queued'}))
        async with fixture() as (sessions,client,admin,payload_hash):
            device,task,_ = await ready(client,admin,payload_hash)
            event = event_for(device,task)
            async def manual():
                async with sessions() as session:
                    actor = await auth._build_context(await session.get(User,9),session)
                    return await api.complete_manual_publication(1001,api.DistributionManualComplete(
                        tenant_id=4,site_id=2,source_version=1,page_url=event['publicUrl']),session,actor,None)
            manual_result, device_result = await asyncio.wait_for(asyncio.gather(manual(),
                client.post(PREFIX+'/device/exchange',headers=device_headers(device,2),
                    json={'contractVersion':1,'deviceId':device['id'],'receipts':[event]})),timeout=10)
            assert manual_result['status'] == 'published' and device_result.status_code == 200
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(SeoPublishAttempt)) == 1
                assert (await session.get(SeoContentPublication,1001)).page_url == event['publicUrl']
    asyncio.run(scenario())


def test_inflight_admin_disable_prevents_pairing_despite_admitted_jwt(monkeypatch):
    async def scenario():
        from app.api import seo_distribution_report as routes
        admitted = asyncio.Event()
        original = routes.management
        async def observed(request,session,ctx,**kwargs):
            admitted.set()
            return await original(request,session,ctx,**kwargs)
        monkeypatch.setattr(routes,'management',observed)
        async with fixture() as (sessions,client,admin,payload_hash):
            async with sessions() as revoker:
                user = await revoker.get(User,9,with_for_update=True)
                user.is_active = False
                await revoker.flush()
                pending = asyncio.create_task(client.post(PREFIX+'/device-pairings'+SCOPE,
                    headers=management_headers(admin),json={'label':'Synthetic computer','platform':'wechat-article',
                        'account_id':'seo-connection-40','expected_revision':0}))
                await asyncio.wait_for(admitted.wait(),timeout=5)
                await revoker.commit()
                response = await asyncio.wait_for(pending,timeout=10)
                assert response.status_code == 403
            async with sessions() as session:
                module = await session.get(TenantModule,1)
                assert not registry(module.module_settings,initialize=True)['pairings']
    asyncio.run(scenario())


def test_claim_map_saturation_and_forged_credentials_do_not_poison_device_budget():
    async def scenario():
        async with fixture() as (sessions,client,admin,payload_hash):
            device,task,_ = await ready(client,admin,payload_hash)
            _claim_rates.clear()
            for i in range(2048):
                limit('synthetic-probing-code-'+str(i),1,claim=True)
            with pytest.raises(HTTPException):
                limit('synthetic-new-peer',1,claim=True)
            before = dict((k,len(v)) for k,v in _rates.items())
            for _ in range(3):
                invalid = {**device,'credential':report.secrets.token_urlsafe(48)}
                response = await client.post(PREFIX+'/device/exchange',headers=device_headers(invalid,2),
                    json={'contractVersion':1,'deviceId':device['id'],'receipts':[]})
                assert response.status_code == 401
            assert before == {k:len(v) for k,v in _rates.items()}
            valid = await client.post(PREFIX+'/device/exchange',headers=device_headers(device,2),
                json={'contractVersion':1,'deviceId':device['id'],'receipts':[]})
            assert valid.status_code == 200
    asyncio.run(scenario())


def test_frozen_pairing_bindings_schema_and_module_hash_isolation():
    async def scenario():
        async with fixture() as (sessions,client,admin,payload_hash):
            pairing = await pair(client,admin)
            response = await client.post(PREFIX+'/device-pairings/claim',json={
                'pairing_code':pairing['pairing_code'],'request_id':str(uuid4())})
            assert response.status_code == 200
            claim = response.json()
            assert set(claim) == {'schema','pairing_id','claimed_at','device','bindings_configured','automatic_submit'}
            assert claim['schema'] == 1 and claim['automatic_submit'] is False
            device = claim['device']
            assert re.fullmatch(r'[A-Za-z0-9_-]{64}',device['credential'])
            # Bindings are available before enabling reports, but never grants.
            response = await client.post(PREFIX+'/device/bindings',headers=device_headers(device,1),
                json={'device_id':device['id']})
            assert response.status_code == 200
            binding = response.json()
            assert set(binding) == {'schema','device_id','as_of','items','automatic_submit'}
            assert binding['schema'] == 1 and binding['device_id'] == device['id']
            assert binding['items'][0]['module'] == 'seo'
            assert binding['items'][0]['tenant_id'] == 4 and binding['items'][0]['scope_id'] == 2
            foreign = report.secrets.token_urlsafe(48)
            async with sessions() as session:
                session.add(TenantModule(id=2,tenant_id=4,module_code='geo',status='active',
                    module_settings={KEY:{'devices':{'foreign':{'credential_hash':report.sha(foreign)}}}}))
                module = await report.locked_module(session,4)
                state = registry(module.module_settings)
                # An operator-controlled label is never a credential locator.
                state['devices'][device['id']]['label'] = report.sha(foreign)
                report.store(module,state)
                await session.commit()
            response = await client.post(PREFIX+'/device/bindings',
                headers=device_headers({**device,'credential':foreign},2),json={'device_id':device['id']})
            assert response.status_code == 401
            response = await client.post(PREFIX+'/device/bindings',headers=device_headers(device,2),
                json={'device_id':device['id']})
            assert response.status_code == 200
    asyncio.run(scenario())


def test_late_observation_never_reopens_closed_failed_task():
    async def scenario():
        async with fixture() as (sessions,client,admin,payload_hash):
            device,task,task_id = await ready(client,admin,payload_hash)
            failure = event_for(device,task,code='HUMAN_FAILED',status='failed',publicUrl=None)
            result = await client.post(PREFIX+'/device/exchange',headers=device_headers(device,2),
                json={'contractVersion':1,'deviceId':device['id'],'receipts':[failure]})
            assert result.status_code == 200
            observation = {k:v for k,v in failure.items() if k not in {'deviceId','contractVersion','receiptId'}}
            observation.update(observationId=str(uuid4()),sequence=1,code='RISK_CONTROL',status='awaiting-human',evidence='none')
            result = await client.post(PREFIX+'/device/observations',headers=device_headers(device,3),
                json={'observationVersion':1,'deviceId':device['id'],'items':[observation]})
            assert result.status_code == 200
            async with sessions() as session:
                state = registry((await session.get(TenantModule,1)).module_settings)
                assert state['tasks'][task_id]['outcome'] == 'failed'
                assert (await session.get(SeoContentPublication,1001)).status == 'failed'
            result = await client.post(PREFIX+'/device/exchange',headers=device_headers(device,4),
                json={'contractVersion':1,'deviceId':device['id'],'receipts':[]})
            assert result.status_code == 200 and not result.json()['grants']
            result = await client.post(PREFIX+'/device/exchange',headers=device_headers(device,5),
                json={'contractVersion':1,'deviceId':device['id'],'receipts':[event_for(device,task,sequence=4)]})
            assert result.status_code == 409 and 'receiptAcks' not in result.json()
    asyncio.run(scenario())


def test_reopening_tenant_does_not_reactivate_another_site():
    async def scenario():
        async with fixture() as (sessions,client,admin,payload_hash):
            await ready(client,admin,payload_hash)
            other_scope = '?tenant_id=4&site_id=3'
            response = await client.put(PREFIX+'/settings'+other_scope,headers=management_headers(admin),
                json={'enabled':True,'scope_enabled':True,'expected_revision':2,'expected_scope_revision':0})
            assert response.status_code == 200
            response = await client.put(PREFIX+'/settings'+SCOPE,headers=management_headers(admin),
                json={'enabled':False,'scope_enabled':False,'expected_revision':3,'expected_scope_revision':1})
            assert response.status_code == 200
            response = await client.put(PREFIX+'/settings'+SCOPE,headers=management_headers(advisor_bearer()),
                json={'enabled':True,'scope_enabled':True,'expected_revision':4,'expected_scope_revision':2})
            assert response.status_code == 200 and response.json()['scope_enabled'] is True
            response = await client.get(PREFIX+'/settings'+other_scope,headers=management_headers(admin))
            assert response.status_code == 200 and response.json()['scope_enabled'] is False
            assert response.json()['scope_revision'] == 2
    asyncio.run(scenario())
