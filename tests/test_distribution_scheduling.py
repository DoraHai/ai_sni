"""Account admission and crash ambiguity, with real PostgreSQL transactions."""
import asyncio
from copy import deepcopy
from datetime import datetime
from uuid import uuid4
from types import MethodType

from test_distribution_control_postgres import fixture, prepare, device_exchange, receipt, SCOPE, core


def timestamp(value): return int(datetime.fromisoformat(value).timestamp()*1000)


async def config(f,binding,revision=1,**changes):
    value={'binding_id':binding,'expected_revision':revision,'enabled':True,'timezone':'Asia/Shanghai',
        'min_interval_seconds':0,'daily_limit':10,'windows':[{'start':0,'end':1440}],'request_id':str(uuid4()),**changes}
    return await f.call('POST','/account-policy',actor=8,json=value)


def variants(f):
    async def load(self,db,actor,tenant,scope,variant,platform):
        await self.authorize_scope(db,actor,tenant,scope)
        return {**SCOPE,'variant_id':variant,'source_revision':self.content['version'],'content':deepcopy(self.content)}
    f.sources.load_source=MethodType(load,f.sources)


def test_policy_required_and_foreign_roles_cannot_configure(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            device,req=await prepare(f,'handoff'); req.update(action='publish',confirm_manual_publication=True)
            assert (await f.call('POST','/tasks',json=req)).status_code==200
            assert not (await device_exchange(f,device)).json()['tasks']
            response=await f.call('GET','/account-schedules',params=SCOPE)
            assert response.json()['items'][0]['reason']=='POLICY_REQUIRED'
            assert (await config(f,req['binding_id'],0)).status_code==200
            assert len((await device_exchange(f,device)).json()['tasks'])==1
            for actor in (7,9):
                assert (await f.call('GET','/account-policies',actor=actor)).status_code==403
                assert (await f.call('GET','/admin-events',actor=actor)).status_code==403
                data={'binding_id':req['binding_id'],'expected_revision':1,'enabled':True,'timezone':'UTC','min_interval_seconds':0,
                    'daily_limit':100,'windows':[{'start':0,'end':1440}],'request_id':str(uuid4())}
                assert (await f.call('POST','/account-policy',actor=actor,json=data)).status_code==403
            log=(await f.call('GET','/admin-events',actor=8)).json()['items']
            assert any(e['action']=='account_policy_saved' for e in log)
            assert all('credential' not in e['target'] and 'content' not in e['target'] for e in log)
    asyncio.run(run())


def test_windows_interval_day_limit_and_timezone_rollover(monkeypatch):
    async def run():
        clock=[timestamp('2026-10-11T00:00:00+00:00')]; monkeypatch.setattr(core,'now_ms',lambda:clock[0])
        async with fixture(monkeypatch) as f:
            variants(f); device,req=await prepare(f,'publish')
            assert (await config(f,req['binding_id'],windows=[{'start':600,'end':660}],daily_limit=1)).status_code==200
            req['expires_in_seconds']=86400
            assert (await f.call('POST','/tasks',json=req)).status_code==200
            assert not (await device_exchange(f,device)).json()['tasks']
            view=(await f.call('GET','/account-schedules',params=SCOPE)).json()['items'][0]
            assert view['reason']=='OUTSIDE_WINDOW' and view['next_allowed_at']==timestamp('2026-10-11T02:00:00+00:00')
            clock[0]=view['next_allowed_at']
            task=(await device_exchange(f,device)).json()['tasks'][0]
            done=receipt(task,'succeeded','HUMAN_PUBLISHED',evidence='human-reported',url='https://mp.weixin.qq.com/s/synthetic')
            assert (await device_exchange(f,device,[done])).status_code==200
            next_req={**req,'variant_id':12,'request_id':str(uuid4())}
            assert (await f.call('POST','/tasks',json=next_req)).status_code==200
            assert not (await device_exchange(f,device)).json()['tasks']
            view=(await f.call('GET','/account-schedules',params=SCOPE)).json()['items'][0]
            assert view['system_used_today']==1 and view['system_remaining']==0 and view['platform_remaining'] is None
            assert view['next_allowed_at']==timestamp('2026-10-12T02:00:00+00:00')
    asyncio.run(run())


def test_cross_device_account_serialization_and_pause(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            variants(f); d1,r1=await prepare(f,'publish'); d2,r2=await prepare(f,'publish'); r2['variant_id']=12
            assert (await f.call('POST','/tasks',json=r1)).status_code==200
            assert (await f.call('POST','/tasks',json=r2)).status_code==200
            result=await asyncio.gather(device_exchange(f,d1),device_exchange(f,d2))
            assert sum(len(r.json()['tasks']) for r in result)==1
            winner=next((d,r.json()['tasks'][0]) for d,r in zip((d1,d2),result) if r.json()['tasks'])
            d,task=winner
            schedules=(await f.call('GET','/account-policies',actor=8)).json()['items']
            assert sum(s['reason']=='ACCOUNT_BUSY' for s in schedules)==2
            pause={'binding_id':r1['binding_id'],'expected_revision':1,'action':'pause','request_id':str(uuid4())}
            assert (await f.call('POST','/account-pause',actor=8,json=pause)).status_code==200
            envelope=(await device_exchange(f,d)).json()
            assert task['id'] in envelope['pausedTaskIds']
            pause.update(expected_revision=2,action='resume',request_id=str(uuid4()))
            assert (await f.call('POST','/account-pause',actor=8,json=pause)).status_code==200
            assert task['id'] not in (await device_exchange(f,d)).json()['pausedTaskIds']
    asyncio.run(run())


def test_advisor_restriction_cannot_expand_admin_policy(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            d,req=await prepare(f,'publish')
            assert (await config(f,req['binding_id'],min_interval_seconds=600,daily_limit=5)).status_code==200
            restriction={**SCOPE,'binding_id':req['binding_id'],'expected_revision':0,'min_interval_seconds':1200,
                'daily_limit':2,'request_id':str(uuid4())}
            first=await f.call('POST','/account-restriction',json=restriction)
            assert first.status_code==200 and first.json()['schedule']['effective_daily_limit']==2
            assert (await f.call('POST','/account-restriction',json=restriction)).json()==first.json()
            restriction.update(expected_revision=1,daily_limit=6,request_id=str(uuid4()))
            assert (await f.call('POST','/account-restriction',json=restriction)).status_code==403
            restriction.update(daily_limit=2,min_interval_seconds=599,request_id=str(uuid4()))
            assert (await f.call('POST','/account-restriction',json=restriction)).status_code==403
    asyncio.run(run())


def test_unknown_survives_next_day_and_requires_explicit_reconciliation(monkeypatch):
    async def run():
        clock=[timestamp('2026-10-11T04:00:00+00:00')]; monkeypatch.setattr(core,'now_ms',lambda:clock[0])
        async with fixture(monkeypatch) as f:
            variants(f); device,req=await prepare(f,'publish')
            assert (await f.call('POST','/tasks',json=req)).status_code==200
            task=(await device_exchange(f,device)).json()['tasks'][0]
            assert (await device_exchange(f,device,[receipt(task,'unknown','CRASH_RESULT_UNKNOWN')])).status_code==200
            clock[0]+=86400000
            view=(await f.call('GET','/account-schedules',params=SCOPE)).json()['items'][0]
            assert view['reason']=='OUTCOME_UNKNOWN' and view['next_allowed_at'] is None
            data={**SCOPE,'task_id':task['id'],'outcome':'not-published','confirm_platform_checked':True,
                'confirm_executor_stopped':True,'request_id':str(uuid4())}
            assert (await f.call('POST','/task-resolution',json={**data,'confirm_executor_stopped':False})).status_code==422
            assert (await f.call('POST','/task-resolution',actor=9,json=data)).status_code==403
            result=await f.call('POST','/task-resolution',json=data)
            assert result.status_code==200 and result.json()['evidence']=='advisor-reported'
            assert (await f.call('POST','/task-resolution',json=data)).json()==result.json()
            req['request_id']=str(uuid4())
            assert (await f.call('POST','/tasks',json=req)).status_code==200
            assert len((await device_exchange(f,device)).json()['tasks'])==1
            late=receipt(task,'succeeded','HUMAN_PUBLISHED',evidence='human-reported',url='https://mp.weixin.qq.com/s/late')
            late['sequence']=5
            assert (await device_exchange(f,device,[late])).status_code==200
            view=(await f.call('GET','/account-policies',actor=8)).json()['items'][0]
            assert view['policy']['paused_reason']=='RESULT_CONFLICT'
            items=(await f.call('GET','/tasks',params=SCOPE)).json()['items']
            assert all(t['status']=='unknown' and t['revoked'] for t in items)
            correction={**data,'outcome':'published','public_url':'https://mp.weixin.qq.com/s/late','request_id':str(uuid4())}
            assert (await f.call('POST','/task-resolution',json=correction)).status_code==200
            async with f.sessions() as db:
                history=await core.rows(db,'SELECT outcome FROM distribution_task_resolutions WHERE task_id=:id ORDER BY id',id=task['id'])
                assert [r['outcome'] for r in history]==['not-published','published']
            view=(await f.call('GET','/account-schedules',params=SCOPE)).json()['items'][0]
            assert not view['available']
    asyncio.run(run())


def test_captcha_stops_account_but_does_not_release_unknown_publish(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            d,req=await prepare(f,'publish')
            assert (await f.call('POST','/tasks',json=req)).status_code==200
            task=(await device_exchange(f,d)).json()['tasks'][0]
            result=await device_exchange(f,d,[receipt(task,'awaiting-human','CAPTCHA')])
            assert task['id'] in result.json()['pausedTaskIds']
            view=(await f.call('GET','/account-policies',actor=8)).json()['items'][0]
            assert view['policy']['paused_reason']=='CAPTCHA'
            assert (await device_exchange(f,d,[receipt(task,'failed','HUMAN_FAILED')])).status_code==200
            items=(await f.call('GET','/tasks',params=SCOPE)).json()['items']
            assert items[0]['status']=='unknown'
    asyncio.run(run())


def test_dst_day_boundary_and_min_interval_are_absolute():
    from app.distribution_scheduling import day_bounds,next_window
    from zoneinfo import ZoneInfo
    zone=ZoneInfo('America/New_York')
    at=timestamp('2026-11-01T05:00:00+00:00')
    start,end=day_bounds(at,zone)
    assert end-start==25*3600000
    assert next_window(timestamp('2026-03-08T06:59:00+00:00'),zone,[{'start':180,'end':240}])==timestamp('2026-03-08T07:00:00+00:00')


def test_min_interval_persists_after_terminal_publication(monkeypatch):
    async def run():
        clock=[timestamp('2026-10-11T04:00:00+00:00')]; monkeypatch.setattr(core,'now_ms',lambda:clock[0])
        async with fixture(monkeypatch) as f:
            variants(f); d,req=await prepare(f,'publish')
            assert (await config(f,req['binding_id'],min_interval_seconds=600)).status_code==200
            assert (await f.call('POST','/tasks',json=req)).status_code==200
            task=(await device_exchange(f,d)).json()['tasks'][0]
            clock[0]+=60000
            assert (await device_exchange(f,d,[receipt(task,'succeeded','HUMAN_PUBLISHED',evidence='human-reported',url='https://mp.weixin.qq.com/s/one')])).status_code==200
            req.update(variant_id=12,request_id=str(uuid4()))
            assert (await f.call('POST','/tasks',json=req)).status_code==200
            assert not (await device_exchange(f,d)).json()['tasks']
            view=(await f.call('GET','/account-schedules',params=SCOPE)).json()['items'][0]
            assert view['reason']=='MIN_INTERVAL' and view['next_allowed_at']==clock[0]+600000
            clock[0]+=600000
            assert len((await device_exchange(f,d)).json()['tasks'])==1
    asyncio.run(run())


def test_platform_account_tenant_binding_history_cannot_be_reassigned(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            d,req=await prepare(f,'publish')
            assert (await f.call('POST',f"/bindings/{req['binding_id']}/revoke",actor=8,json={})).status_code==200
            value={'module':'seo','tenant_id':5,'scope_id':20,'device_id':d['id'],'account_id':'new-local',
                'external_account_id':'synthetic-public-account','platform':'wechat-article','confirm_account_ownership':True}
            assert (await f.call('POST','/bindings',actor=8,json=value)).status_code==409
    asyncio.run(run())


def test_publication_report_during_account_pause_is_preserved_as_unknown(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            d,req=await prepare(f,'publish')
            assert (await f.call('POST','/tasks',json=req)).status_code==200
            task=(await device_exchange(f,d)).json()['tasks'][0]
            pause={'binding_id':req['binding_id'],'expected_revision':1,'action':'pause','request_id':str(uuid4())}
            assert (await f.call('POST','/account-pause',actor=8,json=pause)).status_code==200
            report=receipt(task,'succeeded','HUMAN_PUBLISHED',evidence='human-reported',url='https://mp.weixin.qq.com/s/pause')
            assert (await device_exchange(f,d,[report])).status_code==200
            item=(await f.call('GET','/tasks',params=SCOPE)).json()['items'][0]
            assert item['status']=='unknown' and item['revoked'] and item['receipt']['publicUrl']==report['publicUrl']
            assert not (await f.call('GET','/account-schedules',params=SCOPE)).json()['items'][0]['available']
    asyncio.run(run())
