"""Real isolated PostgreSQL/JWT queue tests; source metadata is synthetic."""
import asyncio
from types import MethodType
from uuid import uuid4
from copy import deepcopy
from test_distribution_control_postgres import fixture,prepare,SCOPE,core,CONTENT
from app import distribution_queue as queue
from test_distribution_control_postgres import device_exchange,receipt


async def select(f,req,enabled=True,revision=0):
    return await f.call('POST','/project-channel',json={**SCOPE,'binding_id':req['binding_id'],
        'content_type':'article','enabled':enabled,'expected_revision':revision,'request_id':str(uuid4())})


async def permit(f,enabled=True,revision=0,actor=8):
    return await f.call('POST','/channel-permission',actor=actor,json={'platform':'wechat-article','content_type':'article',
        'enabled':enabled,'expected_revision':revision,'request_id':str(uuid4())})


async def read(f):
    response=await f.call('GET','/queue',params=SCOPE)
    assert response.status_code==200,response.text
    return response.json()


def test_automatic_queue_restart_idempotency_and_get_is_read_only(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            _,req=await prepare(f)
            assert (await select(f,req)).status_code==200
            assert not (await read(f))['items']
            await queue.run_once(f.sessions)
            first=(await read(f))['items'][0]
            assert first['state']=='awaiting-authorization'
            for _ in range(3): await queue.run_once(f.sessions)
            assert [q['id'] for q in (await read(f))['items']]==[first['id']]
            assert (await permit(f)).status_code==200
            logs=(await f.call('GET','/admin-events',actor=8)).json()['items']
            entry=next(e for e in logs if e['action']=='channel_permission')
            assert entry['target']=={'platform':'wechat-article','content_type':'article'}
            scoped_logs=(await f.call('GET','/events',params=SCOPE)).json()['items']
            assert not any(e['action']=='channel_permission' for e in scoped_logs)
            await queue.run_once(f.sessions)
            assert (await read(f))['items'][0]['state']=='scheduled' # missing system account policy
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_tasks'))['n']==0
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_publish_reservations'))['n']==0
            assert (await read(f))['scans'][0]['discovery']=='approved-source-polling'
            assert (await f.call('GET','/queue',actor=9,params=SCOPE)).status_code==403
            assert (await f.call('GET','/queue',params={**SCOPE,'tenant_id':5})).status_code==403
    asyncio.run(run())


def test_global_permission_ceiling_scope_and_revoke(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            _,req=await prepare(f,'publish')
            assert (await select(f,req)).status_code==200
            assert (await permit(f,actor=7)).status_code==403
            forged={'platform':'wechat-article','content_type':'article','enabled':True,'expected_revision':0,'request_id':str(uuid4()),'mode':'full-auto'}
            assert (await f.call('POST','/channel-permission',actor=8,json=forged)).status_code==422
            assert (await f.call('POST','/channel-permission',actor=8,json={k:v for k,v in {**forged,'platform':'website-article'}.items() if k!='mode'})).status_code==422
            assert (await permit(f)).status_code==200
            await queue.run_once(f.sessions)
            assert (await read(f))['items'][0]['state']=='awaiting-adaptation'
            assert (await permit(f,False,1)).status_code==200
            await queue.run_once(f.sessions)
            assert (await read(f))['items'][0]['state']=='awaiting-authorization'
            assert (await select(f,req,False,1)).status_code==200
            await queue.run_once(f.sessions)
            assert (await read(f))['items'][0]['reason']=='CHANNEL_DISABLED'
            f.sources.revoked=True
            await queue.run_once(f.sessions)
            assert (await f.call('GET','/queue',params=SCOPE)).status_code==403
            async with f.sessions() as db:
                scan=await core.one(db,'SELECT * FROM distribution_queue_scans')
                assert scan['reason']=='AUTHORIZATION_REVOKED'
    asyncio.run(run())


def intake(f,total=1):
    f.sources.approved=False;f.sources.draft='draft_v1';f.sources.total=total
    async def page(self,db,actor,tenant,scope,platform,*,after_variant_id=None,limit=50):
        await self.authorize_scope(db,actor,tenant,scope)
        ids=list(range(11,self.total+11));remaining=[i for i in ids if i>(after_variant_id or 0)]
        selected=remaining[:limit]
        return {'items':[{'variant_id':i,'draft_version':self.draft,'source_revision':self.content['version'] if self.approved else None,
            'readiness':'ready' if self.approved else 'awaiting-review','reason':'READY' if self.approved else 'REVIEW_REQUIRED'} for i in selected],
            'next_cursor':selected[-1] if len(remaining)>limit else None}
    f.sources.list_intake_candidates=MethodType(page,f.sources)
    async def inspect(self,db,actor,tenant,scope,variant,platform):
        await self.authorize_scope(db,actor,tenant,scope)
        if variant not in range(11,self.total+11): return None
        return {'variant_id':variant,'draft_version':self.draft,'source_revision':self.content['version'] if self.approved else None,
            'readiness':'ready' if self.approved else 'awaiting-review','reason':'READY' if self.approved else 'REVIEW_REQUIRED'}
    f.sources.load_intake_candidate=MethodType(inspect,f.sources)


def test_pending_approval_updates_same_item_and_edit_invalidates_old(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            _,req=await prepare(f,'publish');await select(f,req);await permit(f);intake(f)
            await queue.run_once(f.sessions)
            pending=(await read(f))['items'][0];assert pending['state']=='awaiting-review' and pending['source_revision'] is None
            f.sources.approved=True
            await queue.run_once(f.sessions)
            approved=(await read(f))['items'][0]
            assert approved['id']==pending['id'] and approved['state']=='awaiting-adaptation'
            f.sources.draft='draft_v2';f.sources.content['version']='seo_variant_11_r2';f.sources.content['body']='新版正文'
            await queue.run_once(f.sessions)
            records=(await read(f))['items'];assert len(records)==2
            assert next(q for q in records if q['id']==pending['id'])['state']=='superseded'
    asyncio.run(run())


def test_paginated_restart_discovers_older_than_first_fifty(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            _,req=await prepare(f);await select(f,req);intake(f,121)
            await queue.run_once(f.sessions)
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT next_cursor FROM distribution_queue_scans'))['next_cursor']==60
            await queue.run_once(f.sessions);await queue.run_once(f.sessions)
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_queue'))['n']==121
                assert (await core.one(db,'SELECT next_cursor FROM distribution_queue_scans'))['next_cursor'] is None
            await queue.run_once(f.sessions)
            async with f.sessions() as db: assert (await core.one(db,'SELECT count(*) AS n FROM distribution_queue'))['n']==121
    asyncio.run(run())


def test_pause_binding_revoke_and_source_failure_do_not_create_grants(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            _,req=await prepare(f);await select(f,req);await permit(f)
            await queue.run_once(f.sessions)
            assert (await f.call('POST','/control',json={**SCOPE,'action':'pause','expected_revision':1,'request_id':str(uuid4())})).status_code==200
            await queue.run_once(f.sessions);assert (await read(f))['items'][0]['state']=='paused'
            assert (await f.call('POST','/control',json={**SCOPE,'action':'resume','expected_revision':2,'request_id':str(uuid4())})).status_code==200
            await queue.run_once(f.sessions);assert (await read(f))['items'][0]['state']=='scheduled'
            assert (await f.call('POST','/bindings/'+req['binding_id']+'/revoke',actor=8,json={})).status_code==200
            await queue.run_once(f.sessions);assert (await read(f))['scans'][0]['reason']=='BINDING_UNAVAILABLE'
    asyncio.run(run())


def test_invalid_metadata_fails_closed_without_partial_rows(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            _,req=await prepare(f);await select(f,req);intake(f)
            original=f.sources.list_intake_candidates
            async def bad(*a,**kw):
                result=await original(*a,**kw);result['items'][0]['body']='private body';return result
            f.sources.list_intake_candidates=bad
            await queue.run_once(f.sessions)
            assert not (await read(f))['items']
            assert (await read(f))['scans'][0]['state']=='unavailable'
    asyncio.run(run())


def test_concurrent_workers_persist_cursor_and_do_not_duplicate(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            _,req=await prepare(f);await select(f,req);intake(f,121)
            await asyncio.gather(queue.run_once(f.sessions),queue.run_once(f.sessions),queue.run_once(f.sessions))
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_queue'))['n']==121
                assert (await core.one(db,'SELECT next_cursor FROM distribution_queue_scans'))['next_cursor'] is None
    asyncio.run(run())


def test_unknown_account_holds_queue_and_other_account_continues(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            device,req=await prepare(f,'publish');await select(f,req);await permit(f)
            result=await f.call('POST','/tasks',json=req);assert result.status_code==200,result.text
            task=(await device_exchange(f,device)).json()['tasks'][0]
            r=receipt(task,status='unknown',code='HUMAN_UNKNOWN')
            result=await device_exchange(f,device,[r]);assert result.status_code==200,result.text
            _,other=await prepare(f,'publish',external='second-real-account');await select(f,other)
            await queue.run_once(f.sessions)
            records=(await read(f))['items'];assert len(records)==2
            assert next(q for q in records if q['binding_id']==req['binding_id'])['reason']=='OUTCOME_UNKNOWN'
            assert next(q for q in records if q['binding_id']==other['binding_id'])['state']=='awaiting-adaptation'
            await queue.run_once(f.sessions)
            async with f.sessions() as db:
                assert (await core.one(db,'SELECT count(*) AS n FROM distribution_tasks'))['n']==1
                assert (await core.one(db,"SELECT count(*) AS n FROM distribution_publish_reservations WHERE state='held'"))['n']==1
    asyncio.run(run())


def test_disabled_channel_stops_new_intents_and_audit_does_not_repeat(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            _,req=await prepare(f);await select(f,req);intake(f)
            await queue.run_once(f.sessions);await select(f,req,False,1)
            f.sources.total=2
            await queue.run_once(f.sessions)
            assert len((await read(f))['items'])==1
            assert (await read(f))['items'][0]['state']=='paused'
            async with f.sessions() as db: before=(await core.one(db,'SELECT count(*) AS n FROM distribution_events'))['n']
            await queue.run_once(f.sessions)
            async with f.sessions() as db: assert (await core.one(db,'SELECT count(*) AS n FROM distribution_events'))['n']==before
    asyncio.run(run())


def test_old_pending_variant_point_recheck_marks_superseded(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            _,req=await prepare(f);await select(f,req);intake(f)
            await queue.run_once(f.sessions)
            f.sources.total=0
            await queue.run_once(f.sessions)
            assert (await read(f))['items'][0]['state']=='superseded'
    asyncio.run(run())


def test_canonical_account_selection_deduplicates_devices_and_rebinding_keeps_item(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            _,req=await prepare(f);await select(f,req)
            _,other=await prepare(f)
            assert (await select(f,other)).status_code==409
            await queue.run_once(f.sessions);first=(await read(f))['items'][0]
            await select(f,req,False,1)
            assert (await select(f,other)).status_code==200
            await queue.run_once(f.sessions)
            records=(await read(f))['items'];assert len(records)==1
            assert records[0]['id']==first['id'] and records[0]['binding_id']==other['binding_id']
    asyncio.run(run())


def test_source_ready_flag_cannot_bypass_live_load_gate(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            _,req=await prepare(f);await select(f,req);intake(f);f.sources.approved=True
            async def denied(*args,**kwargs): raise core.problem('source_changed')
            f.sources.load_source=denied
            await queue.run_once(f.sessions)
            assert not (await read(f))['items']
            assert (await read(f))['scans'][0]['reason']=='SOURCE_UNAVAILABLE'
    asyncio.run(run())


def test_queue_recheck_rotates_and_pending_pause_resume_logs_only_changes(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            _,req=await prepare(f);await select(f,req);intake(f,121)
            for _ in range(3): await queue.run_once(f.sessions)
            f.sources.total=0
            for _ in range(4): await queue.run_once(f.sessions)
            async with f.sessions() as db:
                assert (await core.one(db,"SELECT count(*) AS n FROM distribution_queue WHERE state<>'superseded'"))['n']==0
            f.sources.total=1;f.sources.draft='draft_v2'
            await queue.run_once(f.sessions)
            await f.call('POST','/control',json={**SCOPE,'action':'pause','expected_revision':1,'request_id':str(uuid4())})
            await queue.run_once(f.sessions)
            async with f.sessions() as db: before=(await core.one(db,'SELECT count(*) AS n FROM distribution_events'))['n']
            await queue.run_once(f.sessions)
            async with f.sessions() as db: assert (await core.one(db,'SELECT count(*) AS n FROM distribution_events'))['n']==before
            await f.call('POST','/control',json={**SCOPE,'action':'resume','expected_revision':2,'request_id':str(uuid4())})
            await queue.run_once(f.sessions)
            assert next(q for q in (await read(f))['items'] if q['draft_version']=='draft_v2')['state']=='awaiting-review'
    asyncio.run(run())


def test_queue_only_switch_does_not_silently_revoke_legacy_manual_authorization(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            _,req=await prepare(f,'publish');await select(f,req,False)
            assert (await permit(f,False)).status_code==200
            await queue.run_once(f.sessions);assert not (await read(f))['items']
            missing={**req,'confirm_manual_publication':False}
            assert (await f.call('POST','/tasks',json=missing)).status_code==409
            assert (await f.call('POST','/tasks',json=req)).status_code==200
            assert (await f.call('POST','/control',json={**SCOPE,'action':'pause','expected_revision':1,'request_id':str(uuid4())})).status_code==200
            assert (await f.call('POST','/tasks',json={**req,'request_id':str(uuid4())})).status_code==409
    asyncio.run(run())
