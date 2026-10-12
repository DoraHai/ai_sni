"""Actual PG/JWT queue handoff dispatch; normalized attestations are synthetic."""
import asyncio
from uuid import uuid4
import pytest
from test_distribution_control_postgres import fixture,SCOPE,core,device_exchange,receipt,prepare as base_prepare
from test_distribution_planning import model
from test_distribution_queue import select,permit
from app import distribution_queue as queue
from app import distribution_planning as planner,distribution_execution as execution
from app.distribution_execution_capabilities import record_attestation

async def prepare(f,*,attest=True,stage='handoff'):
    device,req=await base_prepare(f,'publish');await select(f,req);await permit(f);await queue.run_once(f.sessions);await planner.run_once(f.sessions,model)
    r=await f.call('POST','/handoff-permission',json={**SCOPE,'binding_id':req['binding_id'],'enabled':True,'stage':stage,'confirm_reviewed_handoff':True,'expected_revision':0,'request_id':str(uuid4())});assert r.status_code==200,r.text
    async with f.sessions() as db:
        b=await core.one(db,'SELECT * FROM distribution_bindings WHERE id=:id',id=req['binding_id'])
        if attest:await record_attestation(db,b['device_id'],'a'*64,'synthetic_fixture_v1',{b['platform']:['handoff','preflight']},core.now_ms()+3600000)
        await db.commit()
    return req,{**b,'credential':device['credential']}

async def progress(f):
    r=await f.call('GET','/execution-progress',params=SCOPE);assert r.status_code==200,r.text;return r.json()

def test_once_configuration_dispatches_once_and_never_grants_publish(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            _,b=await prepare(f)
            await asyncio.gather(execution.run_once(f.sessions),execution.run_once(f.sessions));await execution.run_once(f.sessions)
            p=await progress(f);assert len(p['items'])==1 and p['items'][0]['stage']=='handoff'
            async with f.sessions() as db:
                t=await core.one(db,'SELECT * FROM distribution_tasks');assert t['publication_grant_id'] is None and t['action']=='handoff'
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_publish_reservations'))['n']==0
            assert (await f.call('GET','/execution-progress',actor=9,params=SCOPE)).status_code==403
            r=await f.call('GET','/platform-directory',params=SCOPE);assert r.status_code==200
            assert len(r.json()['items'])==12 and sum(i['native_intake'] for i in r.json()['items'])==2
    asyncio.run(run())

@pytest.mark.parametrize('block',['missing-capability','expired-capability','disabled-config','paused','source-change','revoked'])
def test_invalid_handoff_gates_never_create_task(monkeypatch,block):
    async def run():
        async with fixture(monkeypatch) as f:
            req,b=await prepare(f,attest=block!='missing-capability')
            if block in ('expired-capability','disabled-config'):
                async with f.sessions() as db:
                    sql='UPDATE distribution_capability_attestations SET expires_at=0' if block=='expired-capability' else 'UPDATE distribution_handoff_permissions SET enabled=false'
                    await db.execute(core.text(sql));await db.commit()
            elif block=='paused':assert (await f.call('POST','/control',json={**SCOPE,'action':'pause','expected_revision':1,'request_id':str(uuid4())})).status_code==200
            elif block=='source-change':f.sources.content['body']+='new edit'
            elif block=='revoked':f.sources.revoked=True
            await execution.run_once(f.sessions)
            assert not (await progress(f))['items'] if block!='revoked' else True
            async with f.sessions() as db:assert (await core.one(db,'SELECT count(*) AS n FROM distribution_tasks'))['n']==0
    asyncio.run(run())

def test_device_handoff_receipts_are_idempotent_and_not_publication(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            req,b=await prepare(f,stage='preflight');await execution.run_once(f.sessions)
            device={'id':b['device_id'],'credential':b['credential']}
            envelope=(await device_exchange(f,device)).json();assert len(envelope['tasks'])==1
            task=envelope['tasks'][0];assert task['action']=='preflight' and task['publicationGrantId'] is None
            done=receipt(task,'succeeded','PREFLIGHT_OK')
            first=await device_exchange(f,device,[done]);assert first.status_code==200,first.text
            again=await device_exchange(f,device,[done]);assert again.status_code==200
            await execution.run_once(f.sessions)
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_tasks'))['n']==1
                assert (await core.one(db,'SELECT state FROM distribution_handoff_slots'))['state']=='consumed'
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_publish_reservations'))['n']==0
            assert (await progress(f))['items'][0]['status']=='succeeded'
    asyncio.run(run())

@pytest.mark.parametrize('change',['pause','disable','edit','capability-expiry'])
def test_device_claim_rechecks_configuration_and_version(monkeypatch,change):
    async def run():
        async with fixture(monkeypatch) as f:
            req,b=await prepare(f);await execution.run_once(f.sessions)
            if change=='pause':assert (await f.call('POST','/control',json={**SCOPE,'action':'pause','expected_revision':1,'request_id':str(uuid4())})).status_code==200
            elif change=='edit':f.sources.content['body']+='material edit'
            else:
                async with f.sessions() as db:
                    await db.execute(core.text('UPDATE distribution_handoff_permissions SET enabled=false,revision=revision+1' if change=='disable' else 'UPDATE distribution_capability_attestations SET expires_at=0'));await db.commit()
            device={'id':b['device_id'],'credential':b['credential']}
            envelope=(await device_exchange(f,device)).json()
            if change=='pause':assert envelope['pausedTaskIds']==[str(envelope['tasks'][0]['id'])]
            else:assert not envelope['tasks']
            if change=='pause':
                assert (await f.call('POST','/control',json={**SCOPE,'action':'resume','expected_revision':2,'request_id':str(uuid4())})).status_code==200
                envelope=(await device_exchange(f,device)).json();assert len(envelope['tasks'])==1
    asyncio.run(run())

def test_unknown_handoff_holds_account_and_duplicate_receipts_do_not_retry(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            req,b=await prepare(f);await execution.run_once(f.sessions)
            device={'id':b['device_id'],'credential':b['credential']}
            task=(await device_exchange(f,device)).json()['tasks'][0]
            waiting=receipt(task,'awaiting-human','HUMAN_REQUIRED')
            assert (await device_exchange(f,device,[waiting])).status_code==200
            unknown=receipt(task,'unknown','EXECUTION_RESULT_UNKNOWN')
            assert (await device_exchange(f,device,[unknown])).status_code==200
            assert (await device_exchange(f,device,[unknown])).status_code==200
            await execution.run_once(f.sessions)
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_tasks'))['n']==1
                assert (await core.one(db,'SELECT state FROM distribution_handoff_slots'))['state']=='held'
                assert (await core.one(db,'SELECT status FROM distribution_tasks'))['status']=='unknown'
                from app import distribution_scheduling as scheduling
                assert (await scheduling.schedule(db,b))['reason']=='OUTCOME_UNKNOWN'
    asyncio.run(run())


def test_same_account_on_two_projects_and_devices_is_serialized(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            req,b=await prepare(f)
            from types import MethodType
            from copy import deepcopy
            original=f.sources.authorize_scope
            async def auth(self,db,actor,tenant,scope):
                assert scope in (19,21)
                await original(db,actor,tenant,19)
            async def load(self,db,actor,tenant,scope,variant,platform):
                await self.authorize_scope(db,actor,tenant,scope)
                return {'module':'seo','tenant_id':tenant,'scope_id':scope,'variant_id':variant,'source_revision':self.content['version'],'content':deepcopy(self.content)}
            f.sources.authorize_scope=MethodType(auth,f.sources);f.sources.load_source=MethodType(load,f.sources)
            scope={**SCOPE,'scope_id':21}
            async with f.sessions() as db:
                await db.execute(core.text('INSERT INTO seo_sites SELECT 21,tenant_id FROM seo_sites WHERE id=19'));await db.commit()
            device=(await f.call('POST','/devices',actor=8,json={'label':'second device'})).json()['device']
            r=await f.call('POST','/bindings',actor=8,json={**scope,'device_id':device['id'],'account_id':'second_local','external_account_id':b['external_account_id'],'platform':b['platform'],'confirm_account_ownership':True});assert r.status_code==200,r.text
            binding=r.json()['binding']['id']
            for path,body in [('/control',{'action':'start','expected_revision':0}),('/project-channel',{'binding_id':binding,'content_type':'article','enabled':True,'expected_revision':0}),('/handoff-permission',{'binding_id':binding,'stage':'handoff','enabled':True,'confirm_reviewed_handoff':True,'expected_revision':0})]:
                r=await f.call('POST',path,json={**scope,**body,'request_id':str(uuid4())});assert r.status_code==200,r.text
            async with f.sessions() as db:
                await core.authorize_scope(db,7,scope)
                await db.execute(core.text('INSERT INTO distribution_queue SELECT gen_random_uuid(),tenant_id,module,21,platform,external_account_id,CAST(:binding AS uuid),variant_id,draft_version,source_revision,content_digest,state,reason,next_allowed_at,created_at,checked_at FROM distribution_queue'),{'binding':binding})
                await record_attestation(db,device['id'],'b'*64,'synthetic_fixture_v1',{b['platform']:['handoff']},core.now_ms()+3600000);await db.commit()
            await planner.plan_scope(f.sessions,scope,model)
            await asyncio.gather(execution.run_once(f.sessions),execution.run_once(f.sessions))
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_tasks'))['n']==1
                assert (await core.one(db,"SELECT count(*) AS n FROM distribution_handoff_slots WHERE state='held'"))['n']==1
    asyncio.run(run())
