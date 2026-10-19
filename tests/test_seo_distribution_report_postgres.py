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
