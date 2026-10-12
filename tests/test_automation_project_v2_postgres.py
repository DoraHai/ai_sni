"""Shared v2 native PG boundary tests, synthetic scopes and no supplier calls."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text

from app import automation_projects as core,automation_project_v2 as v2
from app.automation_project_contract import ConfigurationV2,Configure,Control
from test_automation_projects_postgres import database,PG,CONFIG,configure,control,setup


def config(operation='ranking_collect',ident=20):
    return {'contract_version':2,'operations':[operation],
        'targets':[{'operation':operation,'object_type':'keyword','object_id':ident,
            'source_revision':0,'source_hash':'a'*64,'variant':'baidu_desktop'}],
        'service_plan':{'revision':3,'sha256':'b'*64},'source_bindings':[],
        'cycle':{'mode':'daily','enabled':True},'limits':{'max_dispatches_per_run':2,'max_external_calls_per_run':2},
        'stop_condition':'drafts_ready_or_blocked','owner_user_id':7}


@asynccontextmanager
async def fixture():
    async with database() as sessions:
        async with sessions.begin() as db:
            raw=(await (await db.connection()).get_raw_connection()).driver_connection
            await raw.execute((Path(__file__).parents[1]/'scripts/automation_projects_v2_schema.sql').read_text(encoding='utf-8'))
        yield sessions


@pytest.mark.parametrize('patch',[{'operations':['ranking_collect','ranking_collect']},
    {'operations':['wrong_operation']},{'targets':[]},{'limits':{'max_dispatches_per_run':1,'max_external_calls_per_run':101}},
    {'service_plan':{'revision':3,'sha256':'private-source-text'}},{'source_bindings':[{'kind':'https://private','object_id':1,'revision':0,'sha256':'b'*64}]}])
def test_invalid_typed_configuration(patch):
    with pytest.raises(ValidationError): ConfigurationV2.model_validate({**config(),**patch})


@PG
def test_v1_configuration_and_uuid_hash_survive_v2_installation():
    async def scenario():
        async with database() as sessions:
            key=core.scope('seo',4,2)
            request_id=uuid4()
            old=await configure(sessions,key,request_id=request_id)
            async with sessions.begin() as db:
                raw=(await (await db.connection()).get_raw_connection()).driver_connection
                await raw.execute((Path(__file__).parents[1]/'scripts/automation_projects_v2_schema.sql').read_text(encoding='utf-8'))
            # Out-of-band DDL invalidates prepared plans; resume on fresh pools.
            # Never automatically retry a failed application write.
            await sessions.kw['bind'].dispose()
            replay=await configure(sessions,key,request_id=request_id)
            assert replay[1] and replay[2]==old[2]
            project,_,_=await control(sessions,key,'start',1)
            async with sessions.begin() as db:
                token=await core.claim_step(db,key)
                assert await core.begin_dispatch(db,token)
                await core.settle_step(db,token,status='succeeded')
                assert (await core.read_run(db,key,project['current_run_id']))['steps'][0]['kind']=='onsite_ai'
                assert (await core.project_events_page(db,key))['items'][-1]['safe_changes']==[]
                events=(await core.events_page(db,key,project['current_run_id']))['items']
                assert next(e for e in events if e['code']=='step_succeeded')['actor_kind']=='ai'
    asyncio.run(scenario())


@PG
@pytest.mark.parametrize('operation,override,expected',[
    ('ranking_collect',None,'system'),('monthly_report',None,'system'),
    ('site_diagnosis',None,'system'),('indexation_collection',None,'system'),
    ('onsite_ai',None,'ai'),('content_draft',None,'ai'),
    ('content_master_draft','ai','ai'),('content_master_draft','system','system')])
def test_success_event_uses_durable_operation_or_restricted_adapter_actor(operation,override,expected):
    async def scenario():
        async with fixture() as sessions:
            key=core.scope('seo',4,2)
            project,_,_=await configure(sessions,key,config(operation))
            project,_,_=await control(sessions,key,'start',project['version'])
            async with sessions.begin() as db:
                token=await core.claim_step(db,key)
                # Tokens cannot disguise a stored system step as an AI step.
                token['operation']='onsite_ai'
                with pytest.raises(ValueError):
                    await core.settle_step(db,token,status='succeeded',success_actor_kind='human')
                assert await core.settle_step(db,token,status='succeeded',success_actor_kind=override)
                events=(await core.events_page(db,key,project['current_run_id']))['items']
                assert next(e for e in events if e['code']=='step_succeeded')['actor_kind']==expected
    asyncio.run(scenario())


@PG
def test_v2_and_end_project_fail_closed_on_v1_structure():
    async def scenario():
        async with database() as sessions:
            key=core.scope('seo',4,2)
            with pytest.raises(HTTPException) as error: await configure(sessions,key,config())
            assert error.value.status_code==503
            project,_,_=await configure(sessions,key)
            with pytest.raises(HTTPException) as error: await control(sessions,key,'end_project',project['version'])
            assert error.value.status_code==503
            async with sessions() as db:
                assert (await core.read_project(db,key))['cycle_enabled']
                assert not await v2.schema_ready(db)
    asyncio.run(scenario())


@PG
@pytest.mark.parametrize('module',['seo','geo'])
def test_typed_steps_target_fence_receipts_limits_and_restart(module):
    async def scenario():
        async with fixture() as sessions:
            key,project=await setup(sessions,module=module,config=config())
            async with sessions.begin() as db:
                token=await core.claim_step(db,key)
                assert token['task_id'] is None and token['operation']=='ranking_collect'
                with pytest.raises(HTTPException):
                    await core.check_step(db,{**token,'target':{**token['target'],'object_id':999}})
                assert await v2.begin_call(db,token,'batch_1',kind='provider')
            async with sessions.begin() as db:
                assert not await v2.begin_call(db,token,'batch_1',kind='provider')
                assert await v2.finish_call(db,token,'batch_1',state='unknown',fee_state='unknown_charge')
                assert await v2.begin_call(db,token,'batch_2',kind='http')
                assert await v2.finish_call(db,token,'batch_2',state='succeeded',fee_state='not_called')
                with pytest.raises(HTTPException) as error: await v2.begin_call(db,token,'batch_3')
                assert error.value.detail['code']=='automation_external_call_limit'
                await core.settle_step(db,token,status='unknown',fee_state='unknown_charge')
            async with sessions.begin() as db:
                assert await v2.finish_call(db,token,'batch_1',state='succeeded',fee_state='recorded',evidence_refs=['api_event:123'])
                assert not await v2.finish_call(db,token,'batch_1',state='succeeded',fee_state='recorded',evidence_refs=['api_event:123'])
                with pytest.raises(HTTPException): await v2.finish_call(db,token,'batch_1',state='failed',fee_state='recorded')
                run=await core.read_run(db,key,project['current_run_id'])
                assert run['steps'][0]['status']=='unknown' and run['steps'][0]['fee_state']=='recorded'
                events=await core.events_page(db,key,run['id'])
                assert any(e['code']=='external_call_late_receipt' for e in events['items'])
    asyncio.run(scenario())


@PG
@pytest.mark.parametrize('started',[True,False])
def test_end_project_stops_cycle_and_late_receipts_do_not_resume(started):
    async def scenario():
        async with fixture() as sessions:
            key=core.scope('seo',4,2)
            project,_,_=await configure(sessions,key,config())
            if started:
                project,_,_=await control(sessions,key,'start',project['version'])
                async with sessions.begin() as db:
                    token=await core.claim_step(db,key)
                    await v2.begin_call(db,token,'one')
            request_id=uuid4()
            ended,_,applied=await control(sessions,key,'end_project',project['version'],request_id=request_id)
            assert not ended['cycle_enabled'] and ended['next_due_at'] is None and ended['ended_at'] is not None
            assert ended['state']==('ending' if started else 'idle')
            if started:
                async with sessions.begin() as db:
                    with pytest.raises(HTTPException): await v2.begin_call(db,token,'two')
                    await v2.finish_call(db,token,'one',state='succeeded',fee_state='recorded',evidence_refs=['seo_rank_snapshot:123'])
                    await core.settle_step(db,token,status='succeeded',fee_state='recorded')
                    assert (await core.read_run(db,key,project['current_run_id']))['steps'][0]['status']=='stale'
            replay=await control(sessions,key,'end_project',project['version'],request_id=request_id)
            assert replay[1] and replay[2]==applied and replay[0]['state']=='idle'
            async with sessions() as db:
                assert await v2.ownership(db,key,'ranking_collect') is not None
            with pytest.raises(HTTPException): await control(sessions,key,'start',replay[0]['version'])
            async with sessions() as db:
                events=(await core.project_events_page(db,key))['items']
                end=next(e for e in events if e['code']=='project_end_project')
                assert any(d['path']=='ended_at' and d['after'] for d in end['safe_changes'])
            reopened,_,_=await configure(sessions,key,config(),version=replay[0]['version'])
            assert reopened['ended_at'] is None and reopened['state']=='not_started'
    asyncio.run(scenario())


@PG
def test_configuration_difference_audit_and_legacy_downgrade_rejection():
    async def scenario():
        async with fixture() as sessions:
            key=core.scope('geo',4,2)
            first=config()
            project,_,_=await configure(sessions,key,first)
            revised=deepcopy(first)
            revised['service_plan']['revision']=4
            revised['limits']['max_external_calls_per_run']=3
            project,_,_=await configure(sessions,key,revised,version=project['version'])
            async with sessions() as db:
                changes=(await core.project_events_page(db,key))['items'][-1]['safe_changes']
                assert {'path':'configuration.service_plan','before':first['service_plan'],'after':revised['service_plan']} in changes
                assert not any(k in json.dumps(changes) for k in ['prompt','password','api_key'])
            with pytest.raises(HTTPException) as error:
                await configure(sessions,key,CONFIG,version=project['version'])
            assert error.value.detail['code']=='automation_contract_downgrade'
    asyncio.run(scenario())


@PG
def test_event_failure_rolls_back_v2_call_admission():
    async def scenario():
        async with fixture() as sessions:
            key,_=await setup(sessions,config=config())
            async with sessions.begin() as db:
                token=await core.claim_step(db,key)
                await db.execute(text("CREATE FUNCTION reject_calls() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'log unavailable'; END $$"))
                await db.execute(text('CREATE TRIGGER reject_calls BEFORE INSERT ON automation_project_events FOR EACH ROW EXECUTE FUNCTION reject_calls()'))
            with pytest.raises(Exception,match='log unavailable'):
                async with sessions.begin() as db: await v2.begin_call(db,token,'blocked')
            async with sessions() as db:
                run=await core.read_run(db,key,token['run_id'])
                assert run['steps'][0]['calls']==[]
    asyncio.run(scenario())


@PG
def test_export_high_water_scope_bound_and_no_write():
    async def scenario():
        async with fixture() as sessions:
            key,project=await setup(sessions,config=config())
            async with sessions() as db: page=await v2.events_export_page(db,key,limit=1)
            assert page['next_after_id'] and page['snapshot_upper_id']
            await control(sessions,key,'disable_cycle',project['version'])
            async with sessions.begin() as db:
                await db.execute(text('SET TRANSACTION READ ONLY'))
                rest=await v2.events_export_page(db,key,after_id=page['next_after_id'],through_id=page['snapshot_upper_id'])
                assert all(row['code']!='project_disable_cycle' for row in rest['items'])
                foreign=await v2.events_export_page(db,core.scope('geo',4,2),through_id=page['snapshot_upper_id'])
                assert foreign['items']==[]
                assert 'safe_changes' in v2.csv_export(page).splitlines()[0]
                with pytest.raises(HTTPException): await v2.events_export_page(db,key,limit=501)
    asyncio.run(scenario())


@pytest.mark.parametrize('value',['=SUM(1,2)',' +1','\t@cmd','\ufeff-1'])
def test_csv_formula_safety(value):
    result=v2.csv_export({'items':[{'code':value}]})
    assert "'"+value in result or "'"+value.replace('"','""') in result


@pytest.mark.parametrize('path,value',[('state','prompt=SECRET'),('configuration.targets',[{'url':'https://private'}]),
    ('configuration.service_plan',{'secret':'API_KEY'}),('configuration.task_ids',['secret']),('configuration.operations',['https://private']),
    ('configuration.cycle',{'mode':'once','enabled':True}),('ended_at','private note')])
def test_audit_rejects_arbitrary_bodies(path,value):
    with pytest.raises((ValueError,TypeError)): v2.validate_changes([{'path':path,'before':None,'after':value}])


@PG
def test_health_counts_are_real_and_unified_heartbeat_is_not_invented():
    async def scenario():
        async with fixture() as sessions:
            key,project=await setup(sessions,config=config())
            async with sessions.begin() as db:
                token=await core.claim_step(db,key)
                await v2.begin_call(db,token,'provider')
            async with sessions() as db:
                health=await v2.health_snapshot(db,'seo')
                assert health['counts']=={'projects':1,'runs':1,'pending_human':0,'unknown_cost':1}
                assert health['rows'][0]['unknown_cost']==1
                assert health['scope']=={'kind':'global','tenant_id':None}
                assert health['overall']=='unverified' and not health['worker']['verified']
                assert all(health['queue'][field] is None for field in ('queued','running','unknown'))
                assert (await v2.health_snapshot(db,'geo'))['counts']['projects']==0
            async with sessions.begin() as db:
                await v2.finish_call(db,token,'provider',state='succeeded',fee_state='recorded')
                await core.settle_step(db,token,status='succeeded',fee_state='recorded')
            async with sessions() as db:
                health=await v2.health_snapshot(db,'seo')
                assert health['counts']=={'projects':1,'runs':1,'pending_human':1,'unknown_cost':0}
    asyncio.run(scenario())


@PG
def test_missing_schema_health_nullable_and_ownership_partial_fails_closed():
    async def scenario():
        async with database(install=False) as sessions:
            async with sessions() as db:
                health=await v2.health_snapshot(db,'seo')
                assert health['state']=='schema_pending' and all(v is None for v in health['counts'].values())
                assert await v2.ownership(db,core.scope('seo',4,2),'ranking_collect') is None
            async with sessions.begin() as db:
                await db.execute(text('CREATE TABLE automation_projects (id bigint)'))
                with pytest.raises(HTTPException): await v2.ownership(db,core.scope('seo',4,2),'ranking_collect')
    asyncio.run(scenario())


@PG
def test_health_truncation_does_not_truncate_global_counts():
    async def scenario():
        async with fixture() as sessions:
            async with sessions.begin() as db:
                await db.execute(text('''INSERT INTO automation_projects(module,tenant_id,scope_id,owner_user_id,configuration)
                    SELECT 'seo',4,value,7,CAST(:config AS jsonb) FROM generate_series(1,55) value'''),{'config':json.dumps(config())})
            async with sessions() as db:
                result=await v2.health_snapshot(db,'seo')
                assert result['counts']['projects']==55 and result['truncated'] and len(result['rows'])==50
                assert all(row['run_state'] is None for row in result['rows'])
    asyncio.run(scenario())


@PG
def test_concurrent_call_key_is_admitted_once():
    async def scenario():
        async with fixture() as sessions:
            key,_=await setup(sessions,config=config())
            async with sessions.begin() as db: token=await core.claim_step(db,key)
            async def one():
                async with sessions.begin() as db: return await v2.begin_call(db,token,'same')
            assert sum(await asyncio.gather(*(one() for _ in range(8))))==1
    asyncio.run(scenario())


@PG
def test_legacy_gate_serializes_first_configuration_and_retains_ended_ownership():
    async def scenario():
        async with fixture() as sessions:
            key=core.scope('seo',4,2)
            async with sessions.begin() as db:
                await v2.check_legacy(db,key,'ranking_collect')
                pending=asyncio.create_task(configure(sessions,key,config()))
                await asyncio.sleep(0.05)
                assert not pending.done()
            project,_,_=await pending
            await control(sessions,key,'end_project',project['version'])
            async with sessions.begin() as db:
                with pytest.raises(HTTPException) as error: await v2.check_legacy(db,key,'ranking_collect')
                assert error.value.detail['code']=='automation_legacy_owned'
                await v2.check_legacy(db,key,'unadopted_operation')
                await v2.check_legacy(db,core.scope('geo',4,2),'ranking_collect')
    asyncio.run(scenario())


@PG
def test_configure_cannot_release_old_scheduler_by_removing_operation():
    async def scenario():
        async with fixture() as sessions:
            key=core.scope('seo',4,2)
            project,_,_=await configure(sessions,key,config())
            with pytest.raises(HTTPException) as error:
                await configure(sessions,key,config('monthly_report'),version=project['version'])
            assert error.value.detail['code']=='automation_operation_release_requires_review'
    asyncio.run(scenario())
