import asyncio
from datetime import datetime,timezone,timedelta
import json
import httpx
import pytest
from app import platform_worker_health as health


def payload(module='seo'):
    now=datetime.now(timezone.utc).isoformat()
    return {'schema':1,'module':module,'observed_at':now,
        'worker':{'scope':'this_process','state':'active','enabled':True,'verified':True,
                  'evidence':{'kind':'local_tick','scope':'this_process'},'last_tick_at':now,
                  'last_attempted':2,'last_completed':1,'last_error_code':None},
        'queue':{'state':'available','queued':3,'running':1,'unknown':2,
                 'oldest_queued_at':now,'oldest_running_at':now},'secret':'DO_NOT_EXPOSE'}


@pytest.mark.parametrize('change',[
    {'verified':False},{'evidence':None},{'scope':'whole_service'},{'last_tick_at':None},
    {'last_tick_at':(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()},
    {'last_error_code':'secret=value'},{'enabled':False}])
def test_200_and_queue_do_not_prove_worker_tick(change):
    data=payload();data['worker'].update(change)
    result=health.normalize('seo',data)
    assert result['worker']['state']=='unverified' and not result['worker']['verified']
    assert result['queue']['queued']==3
    assert 'DO_NOT_EXPOSE' not in json.dumps(result)


def test_exact_scope_queue_schema_pending_and_stale_health():
    data=payload();result=health.normalize('seo',data)
    assert result['worker']['verified'] and result['worker']['evidence']=={'kind':'local_tick','scope':'this_process'}
    data['queue']={'state':'schema_pending','queued':123}
    assert health.normalize('seo',data)['queue']['queued'] is None
    data['observed_at']=(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()
    with pytest.raises(ValueError):health.normalize('seo',data)


@pytest.mark.parametrize('failure',['timeout','redirect','unauthorized','oversize','wrong_module','invalid_json'])
def test_fixed_destinations_bounded_reads_and_failure_isolation(monkeypatch,failure):
    calls=[];real_client=httpx.AsyncClient
    async def provider(request):
        calls.append(request)
        assert request.headers['authorization']=='Bearer '+'a'*32
        assert request.url.host=='127.0.0.1'
        if request.url.port==8010:return httpx.Response(200,json=payload('geo'))
        if failure=='timeout':raise httpx.ReadTimeout('PRIVATE',request=request)
        if failure=='redirect':return httpx.Response(302,headers={'location':'https://evil.test/'})
        if failure=='unauthorized':return httpx.Response(401)
        if failure=='oversize':return httpx.Response(200,content=b'x'*(health.MAX_BYTES+1))
        if failure=='wrong_module':return httpx.Response(200,json=payload('geo'))
        return httpx.Response(200,content=b'PRIVATE')
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return real_client(transport=httpx.MockTransport(provider),**kwargs)
    monkeypatch.setattr(health.httpx,'AsyncClient',client)
    result=asyncio.run(health.read_workers('Bearer '+'a'*32))
    assert result['state']=='partial' and len(calls)==2
    sem,seo,geo=result['rows']
    assert sem['transport_state']=='not_connected' and sem['queue']['queued'] is None
    assert geo['worker']['verified'] and seo['worker']['verified'] is False
    assert 'PRIVATE' not in json.dumps(result)
    assert {str(r.url) for r in calls}==set(health.DESTINATIONS.values())


def test_no_identity_means_no_outbound_credentials(monkeypatch):
    def fail(**kwargs):raise AssertionError('network without identity')
    monkeypatch.setattr(health.httpx,'AsyncClient',fail)
    assert asyncio.run(health.read_workers(None))['state']=='not_connected'


def incident_payload():
    data=payload()
    data['worker'].update(state='degraded',last_error_code='worker_batch_failed')
    data['queue'].update(oldest_queued_at=(datetime.now(timezone.utc)-timedelta(minutes=11)).isoformat(),
        oldest_running_at=(datetime.now(timezone.utc)-timedelta(minutes=4)).isoformat())
    return {'schema':1,'state':'partial','rows':[health.empty('sem','not_connected'),health.normalize('seo',data)]}


def test_alert_signals_use_evidence_and_not_observation_time():
    from app.platform_operations import alert_identity
    workers=incident_payload()
    first=health.worker_alerts(workers,alert_identity)
    assert {a['kind'] for a in first}=={'worker_execution','onsite_queue_stale','onsite_running_stale','onsite_business_unknown'}
    assert all(a['tenant_id'] is None for a in first)
    assert '费用请另查调用台账' in next(a['message'] for a in first if a['kind']=='onsite_business_unknown')
    workers['observed_at']=datetime.now(timezone.utc).isoformat()
    workers['rows'][1]['module_observed_at']=datetime.now(timezone.utc).isoformat()
    workers['rows'][1]['worker']['last_tick_at']=datetime.now(timezone.utc).isoformat()
    assert [(a['id'],a['signal']) for a in first]==[(a['id'],a['signal']) for a in health.worker_alerts(workers,alert_identity)]
    workers['rows'][1]['worker']['last_attempted']+=1
    changed=health.worker_alerts(workers,alert_identity)
    assert next(a['signal'] for a in changed if a['kind']=='worker_execution')!=next(a['signal'] for a in first if a['kind']=='worker_execution')


@pytest.mark.parametrize('state',['unverified','not_connected','stopped','schema_pending','fresh_queue','unknown_oldest'])
def test_no_evidence_disabled_or_idle_workers_do_not_create_faults(state):
    from app.platform_operations import alert_identity
    data=payload();data['queue'].update(queued=0,running=0,unknown=0)
    data['worker'].update(state='unverified',verified=False,evidence=None,last_tick_at=None)
    if state=='not_connected':row=health.empty('sem','not_connected')
    else:
        if state=='stopped':data['worker'].update(state='stopped',enabled=False)
        if state=='schema_pending':data['queue']={'state':'schema_pending'}
        if state in {'fresh_queue','unknown_oldest'}:data['queue'].update(queued=1,running=1)
        if state=='unknown_oldest':data['queue'].update(oldest_queued_at=None,oldest_running_at=None)
        row=health.normalize('seo',data)
    assert health.worker_alerts({'rows':[row]},alert_identity)==[]


@pytest.mark.parametrize('state',['timeout','unavailable','unauthorized','invalid'])
def test_read_failure_is_unknown_monitor_evidence_and_stable(state):
    from app.platform_operations import alert_identity
    workers={'observed_at':'first-read','rows':[health.empty('seo',state)]}
    first=health.worker_alerts(workers,alert_identity)
    assert len(first)==1 and first[0]['kind']=='worker_health_read'
    assert '监控读取失败' in first[0]['message'] and '宕机' not in first[0]['message']
    workers['observed_at']='second-read'
    assert first==health.worker_alerts(workers,alert_identity)


def test_native_health_alerts_claim_resolve_refresh_and_reopen_through_http(monkeypatch):
    from uuid import uuid4
    from fastapi import FastAPI
    from app.api import platform_console as console
    from app.security.auth import require_auth
    from tests.test_platform_console import context
    from tests.test_platform_call_guards import native
    async def scenario(factory,other):
        monkeypatch.setattr(console,'async_session_factory',factory)
        workers=incident_payload();calls=[]
        async def read(authorization):
            assert authorization=='Bearer '+'a'*32
            calls.append(authorization)
            workers['observed_at']=datetime.now(timezone.utc).isoformat()
            workers['rows'][1]['module_observed_at']=workers['observed_at']
            return workers
        monkeypatch.setattr(health,'read_workers',read)
        app=FastAPI();app.include_router(console.router)
        app.dependency_overrides[require_auth]=lambda:context(user_id=10)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture',
                                     headers={'Authorization':'Bearer '+'a'*32}) as client:
            async def current():
                response=await client.get('/api/v1/admin/console/snapshot')
                assert response.status_code==200 and response.headers['cache-control']=='no-store, private'
                return next(a for a in response.json()['alerts'] if a['kind']=='onsite_queue_stale')
            alert=await current()
            def command(action,revision,signal):
                return {'request_id':str(uuid4()),'kind':'alert','key':alert['id'],'expected_revision':revision,
                    'value':{'action':action,'note':'已核查任务与执行器证据','signal':signal}}
            result=await client.post('/api/v1/admin/console/operations',json=command('claim',0,alert['signal']))
            assert result.status_code==200 and result.json()['revision']==1
            claimed=await current();assert claimed['handling']['status']=='in_progress' and claimed['handling']['owner_id']==10
            result=await client.post('/api/v1/admin/console/operations',json=command('resolve',1,alert['signal']))
            assert result.status_code==200 and result.json()['revision']==2
            refreshed=await current();assert refreshed['signal']==alert['signal'] and refreshed['handling']['status']=='resolved'
            workers['rows'][1]['queue']['queued']+=1
            reopened=await current()
            assert reopened['id']==alert['id'] and reopened['signal']!=alert['signal']
            assert reopened['handling']['status']=='open' and reopened['handling']['revision']==2
            stale=await client.post('/api/v1/admin/console/operations',json=command('resolve',2,alert['signal']))
            assert stale.status_code==409
            assert len(calls)==7
    native(monkeypatch,scenario)
