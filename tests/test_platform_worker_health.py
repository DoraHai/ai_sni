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
