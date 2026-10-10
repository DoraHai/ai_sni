"""Real PostgreSQL evidence, replay, lock and late-metering races; no paid calls."""
import asyncio
import copy
from decimal import Decimal
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
from uuid import uuid4
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from app import api_controls as controls,api_metering as meter
from app import platform_usage_review as review
from app.api import platform_console as console
from app.api_cost_summary import read_api_costs
from app.platform_history import parse_query,read_history
from app.platform_call_monitor import read_call_monitor
from app.security.auth import require_auth
from starlette.datastructures import QueryParams
from tests.test_platform_console import context
from tests.test_platform_call_guards import native,budget,change


async def install(factory,monkeypatch):
    monkeypatch.setenv('API_USAGE_REVIEW_ENABLED','true')
    async with factory() as s:
        c=await s.connection();raw=(await c.get_raw_connection()).driver_connection
        await raw.execute((Path(__file__).parents[1]/'scripts/api_usage_review_schema.sql').read_text())
        await s.commit()


async def insert(factory,state='unknown',estimated=None):
    event=str(uuid4())
    async with factory() as s:
        await s.execute(text('''INSERT INTO api_usage_events
            (id,tenant_id,user_id,origin,module,operation,provider,endpoint,state,estimated_amount,currency,provider_request_id)
            VALUES(CAST(:id AS uuid),1,10,'background','seo','fixture','test',
            'dashscope.aliyuncs.com/v1/chat/completions',:state,:estimated,:currency,'provider-fixture')'''),
            {'id':event,'state':state,'estimated':estimated,'currency':'CNY' if estimated is not None else None})
        await s.commit()
    return event


def payload(event,*,amount=None,version=0,state='unknown',terminal='error'):
    return {'request_id':str(uuid4()),'event_id':event,'expected_version':version,'expected_state':state,
        'terminal_state':terminal,'provider_request_id':'provider-fixture','verified_amount':amount,
        'currency':'CNY' if amount is not None else None,
        'evidence':{'source':'provider_billing_record' if amount is not None else 'provider_request_record',
            'provider_host':'dashscope.aliyuncs.com','reference':'provider-record:fixture-123',
            'sha256':'a'*64,'summary':'人工核对测试供应商的请求终态与费用证据索引。',
            'observed_at':datetime.now(timezone.utc).isoformat(),'terminal_confirmed':True,
            'zero_charge_confirmed':amount=='0'}}


@pytest.mark.parametrize('original_state',['requested','unknown'])
def test_native_terminal_review_releases_concurrency_but_unknown_money_blocks(monkeypatch,original_state):
    async def scenario(factory,other):
        await install(factory,monkeypatch)
        event=await insert(factory,original_state,estimated=3)
        data=payload(event,state=original_state)
        async with factory() as s:
            first=await review.mutate_review(s,10,data)
            assert first['row']['state']=='error' and first['row']['review_version']==1
        async with other() as s:
            spent=await controls.usage(s,'global')
            assert spent['active_calls']==0 and spent['unresolved_calls']==1
            assert controls.budget_status(budget(max_concurrent=1),spent)=='normal'
            assert controls.budget_status(budget(monthly_cny='100'),spent)=='unknown'
            assert (await review.mutate_review(s,10,data))['replayed'] is True
            assert await s.scalar(text('SELECT count(*) FROM api_usage_review_audit'))==1
            assert await s.scalar(text('SELECT estimated_amount FROM api_usage_events'))==3
            money=payload(event,state='error',version=1,amount='0')
            result=await review.mutate_review(s,10,money)
            assert Decimal(result['row']['verified_amount'])==0 and result['row']['review_version']==2
            assert (await controls.usage(s,'global'))['unresolved_calls']==0
            costs=await read_api_costs(s)
            assert Decimal(costs['estimated_amount'])==3 and Decimal(costs['known_amount'])==0
            assert Decimal(costs['verified_amount'])==0 and costs['actual_amount'] is None
            history=await read_history(s,parse_query(QueryParams('')))
            assert history['rows'][0]['review_version']==2 and history['rows'][0]['estimated_amount']=='3.000000000000'
            assert (await read_call_monitor(s))['summary']['unresolved_charges']==0
    native(monkeypatch,scenario)


@pytest.mark.parametrize('mismatch',['version','state','host','provider_id','early_evidence','terminal'])
def test_native_conflicting_or_unrelated_evidence_never_releases(monkeypatch,mismatch):
    async def scenario(factory,other):
        await install(factory,monkeypatch);event=await insert(factory)
        data=payload(event)
        if mismatch=='version':data['expected_version']=1
        if mismatch=='state':data['expected_state']='requested'
        if mismatch=='host':data['evidence']['provider_host']='other.test'
        if mismatch=='provider_id':data['provider_request_id']='another-request'
        if mismatch=='early_evidence':data['evidence']['observed_at']=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
        if mismatch=='terminal':data['evidence']['terminal_confirmed']=False
        async with factory() as s:
            with pytest.raises((controls.ControlConflict,ValueError)):
                await review.mutate_review(s,10,data)
            await s.rollback()
            assert await s.scalar(text('SELECT state FROM api_usage_events'))=='unknown'
            assert await s.scalar(text('SELECT count(*) FROM api_usage_review_audit'))==0
    native(monkeypatch,scenario)


@pytest.mark.parametrize('bad',['zero_without_proof','request_only_money','null_zero','wrong_currency','no_sha','credential_url'])
def test_money_and_evidence_require_explicit_human_attestation(bad):
    data=payload(str(uuid4()),amount='0')
    if bad=='zero_without_proof':data['evidence']['zero_charge_confirmed']=False
    if bad=='request_only_money':data['evidence']['source']='provider_request_record'
    if bad=='null_zero':data['verified_amount']=data['currency']=None
    if bad=='wrong_currency':data['currency']='USD'
    if bad=='no_sha':data['evidence']['sha256']=''
    if bad=='credential_url':data['evidence']['reference']='https://user:PRIVATE@provider.test/bill?token=PRIVATE'
    with pytest.raises(ValueError):review.validate(data)


def test_native_same_uuid_replay_and_two_admins_version_race(monkeypatch):
    async def scenario(factory,other):
        await install(factory,monkeypatch);event=await insert(factory)
        data=payload(event,amount='1.25')
        async def submit(f,data,actor=10):
            async with f() as s:return await review.mutate_review(s,actor,data)
        results=await asyncio.gather(submit(factory,data),submit(other,data))
        assert sorted(r['replayed'] for r in results)==[False,True]
        async with factory() as s:
            assert await s.scalar(text('SELECT count(*) FROM api_usage_review_audit'))==1
        with pytest.raises(controls.ControlConflict):await submit(other,data,20)
        modified=copy.deepcopy(data);modified['verified_amount']='2'
        with pytest.raises(controls.ControlConflict):await submit(other,modified)
        event=await insert(factory);one=payload(event);two=payload(event)
        results=await asyncio.gather(submit(factory,one),submit(other,two),return_exceptions=True)
        assert sum(isinstance(r,controls.ControlConflict) for r in results)==1
        async with factory() as s:assert await s.scalar(text('SELECT count(*) FROM api_usage_review_audit'))==2
    native(monkeypatch,scenario)


def test_native_late_real_metering_update_cannot_overwrite_manual_review(monkeypatch):
    async def scenario(factory,other):
        await install(factory,monkeypatch)
        await change(factory,'global',budget(max_concurrent=1))
        attempted,release=asyncio.Event(),asyncio.Event();sent=[]
        async def provider(request):
            sent.append(request);attempted.set();await release.wait()
            return httpx.Response(200,json={'id':'provider-fixture','usage':{'prompt_tokens':100,'completion_tokens':1}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            async def call():
                with meter.background_scope(tenant_id=1,user_id=10,module='geo',operation='fixture'):
                    return await meter.metered_request(client,'post','https://dashscope.aliyuncs.com/v1/chat/completions',
                        model='deepseek-v4-flash',json={'messages':[]})
            task=asyncio.create_task(call())
            try:
                await asyncio.wait_for(attempted.wait(),5)
                async with other() as s:
                    event=str(await s.scalar(text('SELECT id FROM api_usage_events')))
                    result=await review.mutate_review(s,10,payload(event,state='requested',amount='0'))
                    assert result['row']['state']=='error'
                release.set();await task
                async with factory() as s:
                    row=(await s.execute(text('SELECT state,estimated_amount,verified_amount,review_version FROM api_usage_events'))).one()
                    assert row.state=='error' and row.estimated_amount is None and row.verified_amount==0 and row.review_version==1
                    assert len(sent)==1 and (await controls.usage(s,'global'))['active_calls']==0
            finally:
                release.set();await asyncio.gather(task,return_exceptions=True)
    native(monkeypatch,scenario)


def test_review_routes_require_named_global_admin_and_hide_payload_errors(monkeypatch):
    monkeypatch.setenv('API_CONTROLS_ENABLED','true');monkeypatch.setenv('API_USAGE_REVIEW_ENABLED','true')
    app=FastAPI();app.include_router(console.router)
    with TestClient(app) as client:
        for path,method in [('/usage/review','post'),('/usage/'+str(uuid4())+'/review','get')]:
            assert getattr(client,method)('/api/v1/admin/console'+path).status_code==401
            app.dependency_overrides[require_auth]=lambda:context(tenant=1)
            assert getattr(client,method)('/api/v1/admin/console'+path).status_code==403
            app.dependency_overrides.clear()
        app.dependency_overrides[require_auth]=lambda:context()
        result=client.post('/api/v1/admin/console/usage/review',content='PRIVATE'*3000)
        assert result.status_code==422 and 'PRIVATE' not in result.text
        monkeypatch.setenv('API_USAGE_REVIEW_ENABLED','false')
        assert client.post('/api/v1/admin/console/usage/review',json={}).status_code==503


def test_native_review_schema_atomic_repeat_and_missing_audit(monkeypatch):
    async def scenario(factory,other):
        async with factory() as s:assert (await review.status(s))['state']=='schema_pending'
        await install(factory,monkeypatch)
        async with factory() as s:
            assert (await review.status(s))['state']=='enabled'
            c=await s.connection();raw=(await c.get_raw_connection()).driver_connection
            with pytest.raises(Exception):await raw.execute((Path(__file__).parents[1]/'scripts/api_usage_review_schema.sql').read_text())
            await s.rollback()
            assert (await review.status(s))['state']=='enabled'
            await s.execute(text('DROP TABLE api_usage_review_audit'));await s.commit()
            assert (await review.status(s))['state']=='schema_pending'
            event=await insert(other)
            with pytest.raises(RuntimeError):await review.mutate_review(s,10,payload(event))
            await s.rollback()
            assert await s.scalar(text('SELECT state FROM api_usage_events'))=='unknown'
    native(monkeypatch,scenario)


def test_native_audit_failure_rolls_back_terminal_and_fee_together(monkeypatch):
    async def scenario(factory,other):
        await install(factory,monkeypatch);event=await insert(factory)
        async with factory() as s:
            await s.execute(text("""CREATE FUNCTION reject_review_audit() RETURNS trigger LANGUAGE plpgsql
                AS $$BEGIN RAISE EXCEPTION 'fixture audit unavailable'; END$$"""))
            await s.execute(text('CREATE TRIGGER reject_review BEFORE INSERT ON api_usage_review_audit FOR EACH ROW EXECUTE FUNCTION reject_review_audit()'))
            await s.commit()
            with pytest.raises(Exception):await review.mutate_review(s,10,payload(event,amount='1'))
            await s.rollback()
        async with other() as s:
            row=(await s.execute(text('SELECT state,review_version,verified_amount FROM api_usage_events'))).one()
            assert row.state=='unknown' and row.review_version==0 and row.verified_amount is None
            assert await s.scalar(text('SELECT count(*) FROM api_usage_review_audit'))==0
    native(monkeypatch,scenario)


def test_native_review_acl_is_append_only_and_ledger_has_no_delete(monkeypatch):
    async def scenario(factory,other):
        await install(factory,monkeypatch);event=await insert(factory)
        role='usage_review_test_'+uuid4().hex
        try:
            async with factory() as s:
                schema=await s.scalar(text('SELECT current_schema()'))
                await s.execute(text('CREATE ROLE '+role+' NOLOGIN'))
                await s.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO {role}'))
                await s.execute(text(f'GRANT SELECT,INSERT,UPDATE ON api_usage_events TO {role}'))
                await s.commit()
                c=await s.connection();raw=(await c.get_raw_connection()).driver_connection
                script=(Path(__file__).parents[1]/'scripts/api_usage_review_permissions.sql').read_text().replace('sem_runtime',role)
                await raw.execute(script);await s.commit()
            async with other() as s:
                await s.execute(text('SET LOCAL ROLE '+role))
                result=await review.mutate_review(s,10,payload(event,amount='0'))
                assert result['row']['state']=='error'
                await s.execute(text('SET LOCAL ROLE '+role))
                assert await s.scalar(text('SELECT count(*) FROM api_usage_review_audit'))==1
                for statement in ['UPDATE api_usage_review_audit SET actor_id=20',
                                  'DELETE FROM api_usage_review_audit','DELETE FROM api_usage_events']:
                    with pytest.raises(Exception):await s.execute(text(statement))
                    await s.rollback();await s.execute(text('SET LOCAL ROLE '+role))
        finally:
            async with factory() as s:
                await s.execute(text('DROP OWNED BY '+role))
                await s.execute(text('DROP ROLE '+role));await s.commit()
    native(monkeypatch,scenario)


def test_native_authenticated_http_contract_private_reads_and_conflicts(monkeypatch):
    async def scenario(factory,other):
        await install(factory,monkeypatch);event=await insert(factory)
        monkeypatch.setattr(console,'async_session_factory',factory)
        app=FastAPI();app.include_router(console.router)
        app.dependency_overrides[require_auth]=lambda:context(user_id=10)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
            result=await client.get('/api/v1/admin/console/usage/'+event+'/review')
            assert result.status_code==200 and result.headers['cache-control']=='no-store, private'
            assert result.json()['row']['can_review'] and result.json()['row']['review_version']==0
            data=payload(event,amount='1.25')
            result=await client.post('/api/v1/admin/console/usage/review',json=data)
            assert result.status_code==200 and result.headers['cache-control']=='no-store, private'
            assert result.json()['replayed'] is False and result.json()['row']['verified_amount']=='1.250000000000'
            assert (await client.post('/api/v1/admin/console/usage/review',json=data)).json()['replayed'] is True
            stale=payload(event)
            conflict=await client.post('/api/v1/admin/console/usage/review',json=stale)
            assert conflict.status_code==409 and conflict.headers['cache-control']=='no-store, private'
            result=await client.get('/api/v1/admin/console/usage/'+event+'/review')
            assert result.json()['row']['can_review'] is False and result.json()['row']['review_version']==1
    native(monkeypatch,scenario)


def test_native_null_original_provider_id_stays_bound_across_terminal_and_fee_reviews(monkeypatch):
    async def scenario(factory,other):
        await install(factory,monkeypatch);event=await insert(factory)
        async with factory() as s:
            await s.execute(text('UPDATE api_usage_events SET provider_request_id=NULL'));await s.commit()
            first=payload(event);first['provider_request_id']='provider-A'
            await review.mutate_review(s,10,first)
        async with other() as s:
            second=payload(event,state='error',version=1,amount='1.25');second['provider_request_id']='provider-B'
            before=dict((await s.execute(text('SELECT * FROM api_usage_events'))).mappings().one())
            audit_before=list((await s.execute(text('SELECT * FROM api_usage_review_audit'))).mappings())
            with pytest.raises(ValueError,match='已冻结'):
                await review.mutate_review(s,10,second)
            await s.rollback()
            assert dict((await s.execute(text('SELECT * FROM api_usage_events'))).mappings().one())==before
            assert list((await s.execute(text('SELECT * FROM api_usage_review_audit'))).mappings())==audit_before
            result=await review.read_review(s,event)
            assert result['row']['provider_request_id'] is None
            assert result['row']['reviewed_provider_request_id']=='provider-A'
            second['provider_request_id']='provider-A'
            result=await review.mutate_review(s,10,second)
            assert result['row']['review_version']==2 and Decimal(result['row']['verified_amount'])==Decimal('1.25')
            assert result['row']['provider_request_id'] is None
            assert (await review.read_review(s,event))['row']['reviewed_provider_request_id']=='provider-A'
    native(monkeypatch,scenario)


@pytest.mark.parametrize('damage',['missing','missing_id','wrong_version'])
def test_native_missing_or_inconsistent_frozen_audit_refuses_fee_review(monkeypatch,damage):
    async def scenario(factory,other):
        await install(factory,monkeypatch);event=await insert(factory)
        async with factory() as s:
            await s.execute(text('UPDATE api_usage_events SET provider_request_id=NULL'));await s.commit()
            first=payload(event);first['provider_request_id']='provider-A'
            await review.mutate_review(s,10,first)
            # Deliberate owner corruption in this isolated schema only. The
            # runtime ACL prohibits these audit UPDATE/DELETE operations.
            if damage=='missing':await s.execute(text('DELETE FROM api_usage_review_audit'))
            if damage=='missing_id':await s.execute(text("UPDATE api_usage_review_audit SET evidence=evidence-'provider_request_id'"))
            if damage=='wrong_version':await s.execute(text('UPDATE api_usage_review_audit SET review_version=2'))
            await s.commit()
        async with other() as s:
            before=dict((await s.execute(text('SELECT * FROM api_usage_events'))).mappings().one())
            count=await s.scalar(text('SELECT count(*) FROM api_usage_review_audit'))
            second=payload(event,state='error',version=1,amount='0');second['provider_request_id']='provider-A'
            with pytest.raises(controls.ControlConflict):await review.mutate_review(s,10,second)
            await s.rollback()
            assert dict((await s.execute(text('SELECT * FROM api_usage_events'))).mappings().one())==before
            assert await s.scalar(text('SELECT count(*) FROM api_usage_review_audit'))==count
            with pytest.raises(controls.ControlConflict):await review.read_review(s,event)
    native(monkeypatch,scenario)
