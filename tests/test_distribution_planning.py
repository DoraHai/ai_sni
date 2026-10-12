"""Durable planner, actual PG/JWT and controlled model replies, no platforms."""
import asyncio
from uuid import uuid4
from copy import deepcopy
from types import MethodType
import pytest
from test_distribution_control_postgres import fixture,prepare,SCOPE,core
from test_distribution_queue import select,permit
from app import distribution_queue as queue,distribution_planning as planner
from app.distribution_planning_gateway import GatewayFailure


async def ready(f):
    _,req=await prepare(f,'publish');await select(f,req);await permit(f);await queue.run_once(f.sessions)
    return req


async def model(snap,ident):
    return {'items':[{'queue_id':i['queue_id'],'at':i['earliest_at']} for i in snap['items']]}


async def view(f):
    r=await f.call('GET','/plans',params=SCOPE);assert r.status_code==200,r.text;return r.json()


def test_normal_restart_and_concurrent_claim_only_call_once(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            await ready(f);calls=[]
            async def counted(snap,ident): calls.append(snap);await asyncio.sleep(.05);return await model(snap,ident)
            await queue.run_once(f.sessions,module='geo')
            await planner.run_once(f.sessions,counted,module='geo')
            assert calls==[]
            await asyncio.gather(planner.run_once(f.sessions,counted),planner.run_once(f.sessions,counted))
            await planner.run_once(f.sessions,counted)
            data=await view(f);assert len(calls)==1 and len(data['items'])==1
            assert data['items'][0]['basis']=='ai' and data['automated_publish'] is False
            assert calls[0]['tenant_id']==4 and calls[0]['actor_id']==7 and len(calls[0]['items'])==1
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_tasks'))['n']==0
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_publish_reservations'))['n']==0
            assert (await f.call('GET','/plans',actor=9,params=SCOPE)).status_code==403
            assert (await f.call('GET','/plans',params={**SCOPE,'tenant_id':5})).status_code==403
    asyncio.run(run())


@pytest.mark.parametrize('response',[{}, {'items':[]},{'items':[{'queue_id':str(uuid4()),'at':0}]},'not JSON'])
def test_invalid_model_output_fallback_is_explicit_and_retry_bounded(monkeypatch,response):
    async def run():
        async with fixture(monkeypatch) as f:
            await ready(f);calls=[]
            async def bad(snap,ident): calls.append(ident);return response
            await planner.run_once(f.sessions,bad)
            data=await view(f);assert data['items'][0]['basis']=='rules' and data['requests'][0]['reason']=='AI_INVALID_OUTPUT'
            for _ in range(3): await planner.run_once(f.sessions,bad)
            assert len(calls)==1
            for _ in range(4):
                async with f.sessions() as db:
                    await db.execute(core.text('UPDATE distribution_plan_requests SET retry_at=0'));await db.commit()
                await planner.run_once(f.sessions,bad)
            assert len(calls)==3
            assert len([p for p in (await view(f))['items'] if p['state']=='planned'])==1
    asyncio.run(run())


@pytest.mark.parametrize('change',['pause','end','disable','global-disable','policy','revoke','edit'])
def test_mid_model_changes_discard_response_without_plan(monkeypatch,change):
    async def run():
        async with fixture(monkeypatch) as f:
            req=await ready(f)
            async def changed(snap,ident):
                if change in ('pause','end'):
                    assert (await f.call('POST','/control',json={**SCOPE,'action':change,'expected_revision':1,'request_id':str(uuid4())})).status_code==200
                elif change=='disable': await select(f,req,False,1)
                elif change=='global-disable': await permit(f,False,1)
                elif change=='policy':
                    async with f.sessions() as db:
                        await db.execute(core.text('UPDATE distribution_account_policies SET daily_limit=1,revision=revision+1'));await db.commit()
                elif change=='revoke': f.sources.revoked=True
                else: f.sources.content['version']='edited_revision';f.sources.content['body']='changed'
                return await model(snap,ident)
            await planner.run_once(f.sessions,changed)
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_plans'))['n']==0
                assert (await core.one(db,'SELECT state FROM distribution_plan_requests'))['state']=='stale'
    asyncio.run(run())


def test_pause_no_work_or_stopped_queue_never_calls_model(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            calls=[]
            async def counted(*a): calls.append(1);return {}
            await planner.run_once(f.sessions,counted)
            req=await ready(f);await select(f,req,False,1)
            await planner.run_once(f.sessions,counted)
            assert not calls
    asyncio.run(run())


def test_multiple_slots_respect_daily_limit_and_interval(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            req=await ready(f)
            async def load(self,db,actor,tenant,scope,variant,platform):
                await self.authorize_scope(db,actor,tenant,scope)
                return {**SCOPE,'variant_id':variant,'source_revision':self.content['version'],'content':deepcopy(self.content)}
            f.sources.load_source=MethodType(load,f.sources)
            async with f.sessions() as db:
                await db.execute(core.text("INSERT INTO distribution_queue SELECT :id,tenant_id,module,scope_id,platform,external_account_id,binding_id,12,draft_version,source_revision,content_digest,state,reason,next_allowed_at,created_at+1,checked_at FROM distribution_queue LIMIT 1"),{'id':uuid4()})
                await db.execute(core.text('UPDATE distribution_account_policies SET daily_limit=1,min_interval_seconds=600,windows=CAST(:windows AS jsonb)'),{'windows':'[{"start":540,"end":600}]'});await db.commit()
            await planner.run_once(f.sessions,model)
            plans=(await view(f))['items'];assert len(plans)==2
            first,second=sorted(p['planned_at'] for p in plans)
            from zoneinfo import ZoneInfo
            assert planner.scheduling.day_bounds(first,ZoneInfo('Asia/Shanghai'))!=planner.scheduling.day_bounds(second,ZoneInfo('Asia/Shanghai'))
            assert second-first>=600000
            from datetime import datetime
            for at in (first,second):
                local=datetime.fromtimestamp(at/1000,ZoneInfo('Asia/Shanghai'))
                assert 540<=local.hour*60+local.minute<600
    asyncio.run(run())


def test_unknown_model_attempt_cannot_repeat(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            await ready(f);calls=[]
            async def unknown(*a):
                calls.append(1);e=RuntimeError();e.provider_attempted=True;raise e
            await planner.run_once(f.sessions,unknown)
            await planner.run_once(f.sessions,unknown)
            assert len(calls)==1 and (await view(f))['requests'][0]['state']=='unknown'
    asyncio.run(run())

def test_more_than_ten_queue_entries_progress_across_restart(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            await ready(f)
            async def load(self,db,actor,tenant,scope,variant,platform):
                await self.authorize_scope(db,actor,tenant,scope)
                return {**SCOPE,'variant_id':variant,'source_revision':self.content['version'],'content':deepcopy(self.content)}
            f.sources.load_source=MethodType(load,f.sources)
            async with f.sessions() as db:
                await db.execute(core.text("INSERT INTO distribution_queue SELECT gen_random_uuid(),tenant_id,module,scope_id,platform,external_account_id,binding_id,g,draft_version,source_revision,content_digest,state,reason,next_allowed_at,created_at+g,checked_at FROM distribution_queue CROSS JOIN generate_series(12,25) g"));await db.commit()
            calls=[]
            async def counted(snap,ident):calls.append(len(snap['items']));return await model(snap,ident)
            await planner.run_once(f.sessions,counted)
            await planner.run_once(f.sessions,counted)
            assert calls==[10,5]
            assert len([p for p in (await view(f))['items'] if p['state']=='planned'])==15
    asyncio.run(run())


def test_more_than_fifty_empty_scopes_rotate_durably(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            await ready(f)
            async with f.sessions() as db:
                await db.execute(core.text("INSERT INTO distribution_controls SELECT tenant_id,module,g,owner_user_id,state,revision FROM distribution_controls CROSS JOIN generate_series(1,65) g WHERE g<>19"));await db.commit()
                # Force the eligible project behind >50 empty scopes.
                await db.execute(core.text('INSERT INTO distribution_planner_scans VALUES(4,\'seo\',19,1,NULL)'));await db.commit()
            calls=[]
            async def counted(snap,ident):calls.append(1);return await model(snap,ident)
            await planner.run_once(f.sessions,counted);assert calls==[]
            await planner.run_once(f.sessions,counted);assert calls==[1]
    asyncio.run(run())


@pytest.mark.parametrize('revoked_binding',[False,True])
def test_more_than_twenty_channels_rotate_and_restart(monkeypatch,revoked_binding):
    async def run():
        async with fixture(monkeypatch) as f:
            req=await ready(f)
            async with f.sessions() as db:
                target=await core.one(db,'SELECT * FROM distribution_bindings WHERE id=:id',id=req['binding_id'])
                # Deterministic UUIDs before the actual populated binding.
                for n in range(1,26):
                    ident='00000000-0000-4000-8000-'+str(n).zfill(12)
                    await db.execute(core.text("INSERT INTO distribution_bindings SELECT CAST(:id AS uuid),tenant_id,module,scope_id,device_id,:account,:external,platform,active,created_by FROM distribution_bindings WHERE id=:target"),{'id':ident,'account':'empty_'+str(n),'external':'empty_'+str(n),'target':target['id']})
                    await db.execute(core.text("INSERT INTO distribution_project_channels SELECT tenant_id,module,scope_id,CAST(:id AS uuid),content_type,enabled,owner_user_id,revision FROM distribution_project_channels WHERE binding_id=:target"),{'id':ident,'target':target['id']})
                if revoked_binding:await db.execute(core.text("UPDATE distribution_bindings SET active=false WHERE id='00000000-0000-4000-8000-000000000001'"))
                await db.commit()
            calls=[]
            async def counted(snap,ident):calls.append(1);return await model(snap,ident)
            await planner.run_once(f.sessions,counted);assert calls==[]
            await planner.run_once(f.sessions,counted);assert calls==[1]
    asyncio.run(run())

@pytest.mark.parametrize('state',['running','unknown'])
def test_changed_batch_cannot_bypass_active_or_unknown_scope_claim(monkeypatch,state):
    async def run():
        async with fixture(monkeypatch) as f:
            await ready(f);calls=[];entered=asyncio.Event();release=asyncio.Event()
            async def held(snap,ident):calls.append(ident);entered.set();await release.wait();return await model(snap,ident)
            task=asyncio.create_task(planner.run_once(f.sessions,held));await entered.wait()
            async with f.sessions() as db:
                await db.execute(core.text("INSERT INTO distribution_queue SELECT gen_random_uuid(),tenant_id,module,scope_id,platform,external_account_id,binding_id,12,draft_version,source_revision,content_digest,state,reason,next_allowed_at,created_at+1,checked_at FROM distribution_queue LIMIT 1"))
                if state=='unknown':await db.execute(core.text("UPDATE distribution_plan_requests SET state='unknown',reason='AI_ATTEMPT_UNKNOWN'"))
                await db.commit()
            await planner.run_once(f.sessions,held);assert len(calls)==1
            release.set();await task
            if state=='unknown':
                async with f.sessions() as db:assert (await core.one(db,'SELECT count(*) AS n FROM distribution_plans'))['n']==0
    asyncio.run(run())


def test_crash_claim_recovery_is_independent_of_new_batch(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            await ready(f)
            async def crash(*a):raise asyncio.CancelledError()
            with pytest.raises(asyncio.CancelledError):await planner.run_once(f.sessions,crash)
            async with f.sessions() as db:
                await db.execute(core.text('UPDATE distribution_plan_requests SET updated_at=0'))
                await db.execute(core.text("INSERT INTO distribution_queue SELECT gen_random_uuid(),tenant_id,module,scope_id,platform,external_account_id,binding_id,12,draft_version,source_revision,content_digest,state,reason,next_allowed_at,created_at+1,checked_at FROM distribution_queue LIMIT 1"));await db.commit()
            calls=[]
            async def counted(*a):calls.append(1);return {}
            await planner.run_once(f.sessions,counted)
            async with f.sessions() as db:assert (await core.one(db,'SELECT state FROM distribution_plan_requests'))['state']=='unknown'
            assert not calls
    asyncio.run(run())


def test_outer_timeout_is_unknown_and_never_retried(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            await ready(f);calls=[];monkeypatch.setattr(planner,'MODEL_TIMEOUT_SECONDS',.01)
            async def slow(*a):calls.append(1);await asyncio.sleep(1)
            await planner.run_once(f.sessions,slow)
            async with f.sessions() as db:
                await db.execute(core.text('UPDATE distribution_plan_requests SET retry_at=0'));await db.commit()
            await planner.run_once(f.sessions,slow)
            assert len(calls)==1 and (await view(f))['requests'][0]['state']=='unknown'
    asyncio.run(run())

@pytest.mark.parametrize('change',['pause','end','disable','revoke'])
def test_unknown_attempt_survives_business_staleness_and_restoration(monkeypatch,change):
    async def run():
        async with fixture(monkeypatch) as f:
            req=await ready(f);calls=[]
            async def uncertain(snap,ident):
                calls.append(1)
                if change in ('pause','end'):
                    assert (await f.call('POST','/control',json={**SCOPE,'action':change,'expected_revision':1,'request_id':str(uuid4())})).status_code==200
                elif change=='disable':await select(f,req,False,1)
                else:f.sources.revoked=True
                exc=RuntimeError('attempted provider failure');exc.provider_attempted=True;raise exc
            await planner.run_once(f.sessions,uncertain)
            async with f.sessions() as db:assert (await core.one(db,'SELECT state FROM distribution_plan_requests'))['state']=='unknown'
            if change=='pause':assert (await f.call('POST','/control',json={**SCOPE,'action':'resume','expected_revision':2,'request_id':str(uuid4())})).status_code==200
            elif change=='disable':await select(f,req,True,2)
            elif change=='revoke':f.sources.revoked=False
            await planner.run_once(f.sessions,uncertain);assert calls==[1]
    asyncio.run(run())

def test_ten_old_publish_tasks_are_excluded_before_queue_limit(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            req=await ready(f)
            async def load(self,db,actor,tenant,scope,variant,platform):
                await self.authorize_scope(db,actor,tenant,scope)
                return {**SCOPE,'variant_id':variant,'source_revision':self.content['version'],'content':deepcopy(self.content)}
            f.sources.load_source=MethodType(load,f.sources)
            r=await f.call('POST','/tasks',json=req);assert r.status_code==200,r.text
            async with f.sessions() as db:
                await db.execute(core.text("INSERT INTO distribution_queue SELECT gen_random_uuid(),tenant_id,module,scope_id,platform,external_account_id,binding_id,g,draft_version,source_revision,content_digest,state,reason,next_allowed_at,created_at+g,checked_at FROM distribution_queue CROSS JOIN generate_series(12,21) g"))
                await db.execute(core.text("INSERT INTO distribution_tasks SELECT (jsonb_populate_record(NULL::distribution_tasks,to_jsonb(t)||jsonb_build_object('id',gen_random_uuid(),'variant_id',g,'grant_id',gen_random_uuid(),'publication_grant_id',gen_random_uuid(),'lease_id',gen_random_uuid(),'request_id',gen_random_uuid()))).* FROM distribution_tasks t CROSS JOIN generate_series(12,20) g"));await db.commit()
            calls=[]
            async def counted(snap,ident):calls.extend(i['variant_id'] for i in snap['items']);return await model(snap,ident)
            await planner.run_once(f.sessions,counted);assert calls==[21]
    asyncio.run(run())
