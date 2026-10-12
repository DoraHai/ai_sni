"""Portable shared-core tests: isolated loopback PostgreSQL, no module imports.

Only SEO_WORKFLOW_TEST_DATABASE_URL / seo_workflow_test is accepted. No app DSN,
provider, production migration, role creation, or customer data is used.
"""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app import automation_projects as core
from app.automation_project_contract import Configuration, Configure, Control

SQL = Path(__file__).resolve().parents[1] / 'scripts/automation_projects_schema.sql'
PG = pytest.mark.skipif(not os.getenv('SEO_WORKFLOW_TEST_DATABASE_URL'), reason='dedicated local PostgreSQL DSN absent')
CONFIG = dict(task_ids=[11,12], operations=['onsite_ai'],cycle=dict(mode='daily',enabled=True),
    limits=dict(max_dispatches_per_run=2),stop_condition='drafts_ready_or_blocked',owner_user_id=7)


def safe_url(raw):
    url = make_url(raw)
    if (url.drivername != 'postgresql+asyncpg' or url.host not in {'127.0.0.1','localhost','::1'}
            or url.database != 'seo_workflow_test' or url.query):
        raise ValueError('Dedicated loopback seo_workflow_test only')
    return url


@asynccontextmanager
async def database(*, install=True):
    assert os.getenv('SEO_WORKFLOW_TEST_ALLOW_SCHEMA_CREATE') == 'yes'
    url = safe_url(os.environ['SEO_WORKFLOW_TEST_DATABASE_URL'])
    schema = 'automation_test_' + uuid4().hex
    engine = create_async_engine(url,pool_size=8,max_overflow=0,connect_args={'server_settings':{
        'search_path':schema,'lock_timeout':'5000','statement_timeout':'15000'}})
    sessions = async_sessionmaker(engine,expire_on_commit=False)
    created = False
    try:
        async with engine.begin() as db:
            await db.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
            await db.execute(text('CREATE TABLE tenants (id bigint PRIMARY KEY)'))
            await db.execute(text('CREATE TABLE users (id bigint PRIMARY KEY)'))
            await db.execute(text('INSERT INTO tenants VALUES (4),(5)'))
            await db.execute(text('INSERT INTO users VALUES (7),(8)'))
            if install:
                raw = await db.get_raw_connection()
                await raw.driver_connection.execute(SQL.read_text(encoding='utf-8'))
        yield sessions
    finally:
        if created:
            assert schema.startswith('automation_test_') and len(schema)==48
            async with engine.begin() as db:
                await db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


async def configure(sessions,key,config=None,version=0,request_id=None):
    request = Configure(tenant_id=key['tenant_id'],request_id=request_id or uuid4(),expected_version=version,
        configuration=config or CONFIG)
    async with sessions.begin() as db:
        return await core.configure_project(db,key,request,7)


async def control(sessions,key,action,version,request_id=None):
    request = Control(tenant_id=key['tenant_id'],request_id=request_id or uuid4(),expected_version=version,action=action)
    async with sessions.begin() as db:
        return await core.control_project(db,key,request,7)


async def setup(sessions,module='seo',config=None,scope_id=2):
    key = core.scope(module,4,scope_id)
    project,_,_ = await configure(sessions,key,config)
    project,_,_ = await control(sessions,key,'start',project['version'])
    return key,project


@pytest.mark.parametrize('url',[
    'postgresql+asyncpg://x:x@example.com/seo_workflow_test',
    'postgresql+asyncpg://x:x@localhost/production',
    'postgresql://x:x@localhost/seo_workflow_test',
    'postgresql+asyncpg://x:x@localhost/seo_workflow_test?host=example.com'])
def test_database_guard(url):
    with pytest.raises(ValueError): safe_url(url)


@pytest.mark.parametrize('field,value',[('task_ids',[True]),('task_ids',[11,11]),('owner_user_id',7.0),
    ('cycle',dict(mode='once',enabled=True)),('cycle',dict(mode='daily',enabled='true')),
    ('limits',dict(max_dispatches_per_run=True)),('limits',dict(max_dispatches_per_run=21))])
def test_configuration_rejects_ambiguous_or_unbounded_input(field,value):
    with pytest.raises(ValidationError): Configuration.model_validate({**CONFIG,field:value})


@PG
@pytest.mark.parametrize('module',['seo','geo'])
def test_default_configuration_idempotency_and_version_races(module):
    async def scenario():
        async with database() as sessions:
            key = core.scope(module,4,2)
            async with sessions.begin() as db:
                assert await core.schema_ready(db)
                assert await core.read_project(db,key) is None
                assert core.project_view(key,None)['allowed_actions']==[]
            ident = uuid4()
            results = await asyncio.gather(*(configure(sessions,key,request_id=ident) for _ in range(6)))
            assert sum(not r[1] for r in results)==1
            assert all(r[0]['version']==1 for r in results)
            starts = await asyncio.gather(*(control(sessions,key,'start',1) for _ in range(6)),return_exceptions=True)
            assert sum(not isinstance(r,Exception) for r in starts)==1
            assert all(r.detail['code']=='automation_version_conflict' for r in starts if isinstance(r,HTTPException))
            async with sessions() as db:
                assert await db.scalar(text('SELECT count(*) FROM automation_project_runs'))==1
            with pytest.raises(HTTPException) as error:
                await configure(sessions,key,{**CONFIG,'task_ids':[12]},request_id=ident)
            assert error.value.detail['code']=='automation_request_conflict'
            replay = await configure(sessions,key,request_id=ident)
            assert replay[1] and replay[2]==1 and replay[0]['version']==2
            request = Control(tenant_id=5,request_id=uuid4(),expected_version=2,action='pause')
            async with sessions.begin() as db:
                with pytest.raises(HTTPException) as error:
                    await core.control_project(db,key,request,7)
                assert error.value.status_code==403
    asyncio.run(scenario())


@PG
@pytest.mark.parametrize('action,waiting,settled',[('pause','pausing','paused'),('takeover','taking_over','taken_over'),('end','ending','idle')])
def test_inflight_stop_fences_late_results_and_preserves_fee_evidence(action,waiting,settled):
    async def scenario():
        async with database() as sessions:
            key,project = await setup(sessions)
            async with sessions.begin() as db:
                token = await core.claim_step(db,key)
                assert await core.begin_dispatch(db,token)
            stopped,_,_ = await control(sessions,key,action,project['version'])
            assert stopped['state']==waiting
            async with sessions.begin() as db:
                assert await core.claim_step(db,key) is None
                with pytest.raises(HTTPException): await core.check_step(db,token)
                assert await core.settle_step(db,token,status='succeeded',evidence_refs=['api_event:123'],
                    fee_state='recorded',result_links=['/api/v1/seo/onsite-tasks/11'])
                run = await core.read_run(db,key,token['run_id'])
                assert run['steps'][0]['status']=='stale' and run['steps'][0]['result_links']==[]
                assert run['steps'][0]['fee_state']=='recorded'
                assert core.run_view(key,run)['run']['completion_evidence'] is None
                finished = await core.read_project(db,key)
                assert finished['state']==settled
                assert finished['cycle_enabled']
                if action=='end':
                    assert finished['next_due_at'] is not None
                    assert run['steps'][1]['status']=='cancelled'
                else:
                    assert run['steps'][1]['status']=='pending'
                events = await core.events_page(db,key,token['run_id'])
                assert any(e['code']=='step_stale' and e['fee_state']=='recorded' for e in events['items'])
            if action!='end':
                await control(sessions,key,'resume',finished['version'])
                async with sessions.begin() as db:
                    next_token = await core.claim_step(db,key)
                    assert next_token['task_id']==12
                    assert next_token['request_id']!=token['request_id']
                    with pytest.raises(HTTPException): await core.begin_dispatch(db,token)
    asyncio.run(scenario())


@PG
def test_concurrent_claim_dispatch_and_restart_never_replay_uncertain_request():
    async def scenario():
        async with database() as sessions:
            key,_ = await setup(sessions)
            async def claim():
                async with sessions.begin() as db: return await core.claim_step(db,key)
            tokens = await asyncio.gather(*(claim() for _ in range(8)))
            assert sum(t is not None for t in tokens)==1
            token = next(t for t in tokens if t)
            async def dispatch():
                async with sessions.begin() as db: return await core.begin_dispatch(db,token)
            admitted = await asyncio.gather(*(dispatch() for _ in range(8)))
            assert sum(admitted)==1
            async with sessions.begin() as db:
                assert await core.begin_dispatch(db,token) is False
                assert await core.claim_step(db,key) is None
                _,run,step = await core.check_step(db,token)
                assert run['dispatch_count']==1 and step['fee_state']=='unknown_charge'
                await core.settle_step(db,token,status='unknown',fee_state='unknown_charge',error_code='provider_outcome_unknown')
                assert await core.settle_step(db,token,status='succeeded') is False
                assert (await core.claim_step(db,key))['task_id']==12
    asyncio.run(scenario())


@PG
def test_limits_cycle_switch_and_end_are_separate_from_acceptance():
    async def scenario():
        async with database() as sessions:
            config = {**CONFIG,'limits':{'max_dispatches_per_run':1}}
            key,project = await setup(sessions,config=config)
            async with sessions.begin() as db: token = await core.claim_step(db,key)
            disabled,_,_ = await control(sessions,key,'disable_cycle',project['version'])
            assert disabled['generation']==project['generation'] and disabled['state']=='active'
            async with sessions.begin() as db:
                await core.check_step(db,token)
                await core.settle_step(db,token,status='succeeded',evidence_refs=['seo_task:11'])
                assert await core.claim_step(db,key) is None
                run = await core.read_run(db,key,token['run_id'])
                assert run['dispatch_count']==1 and run['steps'][1]['blocker']=='dispatch_limit'
            ended,_,_ = await control(sessions,key,'end',disabled['version'])
            assert ended['state']=='idle' and ended['next_due_at'] is None
            assert str(ended['current_run_id'])==token['run_id']
            async with sessions() as db:
                run = await core.read_run(db,key,token['run_id'])
                assert run['state']=='ended' and run['finished_at'] is not None
                assert core.run_view(key,run)['run']['completion_evidence'] is None
    asyncio.run(scenario())


@PG
def test_history_scope_cursor_events_and_reconfigure_preserve_old_runs():
    async def scenario():
        async with database() as sessions:
            key,project = await setup(sessions)
            ids = [project['current_run_id']]
            for _ in range(3):
                project,_,_ = await control(sessions,key,'end',project['version'])
                project,_,_ = await configure(sessions,key,version=project['version'])
                assert project['current_run_id']==ids[-1]
                project,_,_ = await control(sessions,key,'start',project['version'])
                ids.append(project['current_run_id'])
            async with sessions.begin() as db:
                # Deliberately tie timestamps to exercise UUID tiebreak order.
                await db.execute(text("UPDATE automation_project_runs SET created_at='2026-10-11T00:00:00Z'"))
                page = await core.runs_page(db,key,limit=2)
                next_page = await core.runs_page(db,key,before_run_id=page['next_before_run_id'],limit=2)
                found = [row['id'] for row in page['items']+next_page['items']]
                assert found==sorted(map(str,ids),reverse=True)
                assert next_page['next_before_run_id'] is None
                for other in [core.scope('geo',4,2),core.scope('seo',5,2),core.scope('seo',4,3)]:
                    assert (await core.runs_page(db,other))['items']==[]
                    with pytest.raises(HTTPException) as error: await core.runs_page(db,other,ids[0])
                    assert error.value.status_code==404
                    with pytest.raises(HTTPException): await core.events_page(db,other,ids[0])
                first = await core.events_page(db,key,ids[-1],limit=1)
                assert first['next_after_id'] is not None
                second = await core.events_page(db,key,ids[-1],after_id=first['next_after_id'],limit=1)
                assert second['items'][0]['id']>first['items'][0]['id']
                with pytest.raises(HTTPException): await core.events_page(db,key,ids[-1],limit=0)
                with pytest.raises(HTTPException): await core.runs_page(db,key,'bad-uuid')
    asyncio.run(scenario())


@PG
@pytest.mark.parametrize('table',['automation_project_events','automation_project_commands'])
@pytest.mark.parametrize('operation',['UPDATE','DELETE','TRUNCATE'])
def test_audit_rows_are_append_only_even_for_schema_owner(table,operation):
    async def scenario():
        async with database() as sessions:
            await setup(sessions)
            suffix = " SET module='seo'" if operation=='UPDATE' else ''
            statement = f'{operation} {"FROM " if operation=="DELETE" else ""}{table}{suffix}'
            with pytest.raises(Exception,match='append only'):
                async with sessions.begin() as db: await db.execute(text(statement))
    asyncio.run(scenario())


@PG
@pytest.mark.parametrize('damage',['missing','column','trigger','wrong_trigger'])
def test_missing_partial_or_damaged_schema_fails_closed(damage):
    async def scenario():
        async with database(install=damage!='missing') as sessions:
            async with sessions.begin() as db:
                if damage=='column': await db.execute(text('ALTER TABLE automation_project_runs DROP COLUMN steps'))
                if damage=='trigger': await db.execute(text('ALTER TABLE automation_project_events DISABLE TRIGGER automation_events_immutable'))
                if damage=='wrong_trigger':
                    await db.execute(text('DROP TRIGGER automation_events_immutable ON automation_project_events'))
                    await db.execute(text('CREATE TRIGGER automation_events_immutable BEFORE INSERT ON automation_project_events FOR EACH ROW EXECUTE FUNCTION automation_project_immutable()'))
                assert not await core.schema_ready(db)
                with pytest.raises(HTTPException) as error: await core.require_schema(db)
                assert error.value.status_code==503
                view = core.project_view(core.scope('seo',4,2),None,ready=False)
                assert view['state']=='schema_pending' and not view['capabilities']['can_control']
    asyncio.run(scenario())


@PG
def test_event_failure_rolls_back_claim_and_dispatch_admission():
    async def scenario():
        async with database() as sessions:
            key,_ = await setup(sessions)
            async with sessions.begin() as db:
                await db.execute(text("CREATE FUNCTION reject_events() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'test log failure'; END $$"))
                await db.execute(text('CREATE TRIGGER reject_events BEFORE INSERT ON automation_project_events FOR EACH ROW EXECUTE FUNCTION reject_events()'))
            with pytest.raises(Exception,match='test log failure'):
                async with sessions.begin() as db: await core.claim_step(db,key)
            async with sessions.begin() as db:
                run = await core.read_run(db,key,(await core.read_project(db,key))['current_run_id'])
                assert run['dispatch_count']==0 and run['steps'][0]['status']=='pending'
                await db.execute(text('ALTER TABLE automation_project_events DISABLE TRIGGER reject_events'))
                token = await core.claim_step(db,key)
                await db.execute(text('ALTER TABLE automation_project_events ENABLE TRIGGER reject_events'))
            with pytest.raises(Exception,match='test log failure'):
                async with sessions.begin() as db: await core.begin_dispatch(db,token)
            async with sessions() as db:
                _,_,step = await core.check_step(db,token)
                assert step['dispatched_at'] is None
    asyncio.run(scenario())


def test_month_end_cycle_and_default_no_business_completion():
    stamp = datetime(2026,1,31,tzinfo=timezone.utc)
    config = deepcopy(CONFIG)
    config['cycle']['mode']='monthly'
    assert core.next_due(config,stamp).day==28
    config['cycle']['mode']='once'
    assert core.next_due(config,stamp) is None


@PG
def test_review_acl_script_and_missing_runtime_insert_privilege():
    async def scenario():
        async with database() as sessions:
            async with sessions.begin() as db:
                role = await db.scalar(text('SELECT current_user'))
                schema = await db.scalar(text('SELECT current_schema()'))
                quote = lambda value: '"'+value.replace('"','""')+'"'
                acl = SQL.with_name('automation_projects_permissions.sql').read_text(encoding='utf-8')
                acl = acl.replace(':"schema"',quote(schema)).replace(':"runtime_role"',quote(role))
                connection = await db.connection()
                raw = await connection.get_raw_connection()
                await raw.driver_connection.execute(acl)
                assert await core.schema_ready(db)
                assert not await db.scalar(text("SELECT has_table_privilege('automation_project_events','UPDATE')"))
                assert not await db.scalar(text("SELECT has_table_privilege('automation_project_commands','DELETE')"))
                assert not await db.scalar(text("SELECT has_table_privilege('automation_projects','TRUNCATE')"))
            key,_ = await setup(sessions)
            async with sessions.begin() as db:
                token = await core.claim_step(db,key)
                assert await core.begin_dispatch(db,token)
                await db.execute(text('REVOKE INSERT ON automation_project_events FROM CURRENT_USER'))
                assert not await core.schema_ready(db)
                with pytest.raises(HTTPException) as error: await core.claim_step(db,key)
                assert error.value.status_code==503
    asyncio.run(scenario())


@PG
def test_pause_serializes_against_outbound_admission_and_blocks_forged_token():
    async def scenario():
        async with database() as sessions:
            key,project = await setup(sessions)
            async with sessions.begin() as db: token = await core.claim_step(db,key)
            for field,value in [('task_id',999),('owner_user_id',8),('scope_id',3),('tenant_id',5),('module','geo')]:
                async with sessions.begin() as db:
                    with pytest.raises(HTTPException): await core.begin_dispatch(db,{**token,field:value})
            async def dispatch():
                async with sessions.begin() as db: return await core.begin_dispatch(db,token)
            outcomes = await asyncio.gather(dispatch(),control(sessions,key,'pause',project['version']),return_exceptions=True)
            # Exactly one serialized ordering: already admitted, or pause wins.
            assert outcomes[0] is True or isinstance(outcomes[0],HTTPException)
            assert outcomes[1][0]['state']=='pausing'
            async with sessions.begin() as db:
                with pytest.raises(HTTPException): await core.begin_dispatch(db,token)
                events = await core.events_page(db,key,token['run_id'])
                codes = [e['code'] for e in events['items']]
                if 'dispatch_admitted' in codes:
                    assert codes.index('dispatch_admitted')<codes.index('project_pause')
                await core.settle_step(db,token,status='unknown' if outcomes[0] is True else 'cancelled',
                    fee_state='unknown_charge' if outcomes[0] is True else 'not_called')
                assert (await core.read_project(db,key))['state']=='paused'
    asyncio.run(scenario())


@PG
def test_scheduler_stale_start_and_audit_redaction_boundaries():
    async def scenario():
        async with database() as sessions:
            key = core.scope('geo',4,2)
            original,_,_ = await configure(sessions,key)
            project,_,_ = await control(sessions,key,'start',original['version'])
            async with sessions.begin() as db:
                with pytest.raises(HTTPException): await core.start_run(db,key,original,actor_kind='system')
                for kwargs in [dict(code='unsafe\nsecret'),dict(code='ok',evidence_refs=['https://example.com/?key=secret']),
                               dict(code='ok',step_key='arbitrary secret'),dict(code='ok',fee_state='free')]:
                    with pytest.raises(ValueError): await core.append_event(db,key,run_id=project['current_run_id'],**kwargs)
                token = await core.claim_step(db,key)
                with pytest.raises(ValueError):
                    await core.settle_step(db,token,status='failed',error_code='raw supplier password')
                with pytest.raises(ValueError):
                    await core.settle_step(db,token,status='succeeded',result_links=['https://example.com'])
                assert (await core.read_run(db,key,token['run_id']))['steps'][0]['status']=='running'
    asyncio.run(scenario())


@PG
@pytest.mark.parametrize('module',['seo','geo'])
def test_project_events_include_configuration_without_runs_and_read_without_writes(module):
    async def scenario():
        async with database() as sessions:
            key = core.scope(module,4,2)
            async with sessions() as db:
                assert (await core.project_events_page(db,key))['items']==[]
                assert await db.scalar(text('SELECT count(*) FROM automation_projects'))==0
                assert core.project_view(key,None)['capabilities']['schema_state']=='ready'
                pending = core.project_view(key,None,ready=False)
                assert pending['capabilities']['schema_state']=='pending'
                assert pending['state']=='schema_pending' and pending['allowed_actions']==[]
            project,_,_ = await configure(sessions,key)
            project,_,_ = await control(sessions,key,'disable_cycle',project['version'])
            async with sessions() as db:
                page = await core.project_events_page(db,key,limit=1)
                assert page['items'][0]['code']=='project_configure' and page['items'][0]['run_id'] is None
                assert page['next_after_id']==page['items'][0]['id']
                second = await core.project_events_page(db,key,after_id=page['next_after_id'])
                assert second['items'][0]['code']=='project_disable_cycle' and second['items'][0]['run_id'] is None
                assert second['next_after_id'] is None
                assert await db.scalar(text('SELECT count(*) FROM automation_project_runs'))==0
            project,_,_ = await control(sessions,key,'start',project['version'])
            async with sessions() as db:
                page = await core.project_events_page(db,key)
                assert len(page['items'])==4
                assert [e['code'] for e in page['items']]==['project_configure','project_disable_cycle','run_queued','project_start']
                assert page['items'][-1]['run_id']==str(project['current_run_id'])
                run_page = await core.events_page(db,key,project['current_run_id'])
                assert len(run_page['items'])==2
                for other in [core.scope('geo' if module=='seo' else 'seo',4,2),core.scope(module,5,2),core.scope(module,4,3)]:
                    assert (await core.project_events_page(db,other))['items']==[]
                    assert (await core.project_events_page(db,other,after_id=page['items'][0]['id']))['items']==[]
                for kwargs in [dict(limit=0),dict(limit=101),dict(after_id=-1),dict(after_id=True)]:
                    with pytest.raises(HTTPException) as error: await core.project_events_page(db,key,**kwargs)
                    assert error.value.status_code==422
                assert await db.scalar(text('SELECT count(*) FROM automation_projects'))==1
                assert await db.scalar(text('SELECT count(*) FROM automation_project_runs'))==1
                assert await db.scalar(text('SELECT count(*) FROM automation_project_events'))==4
                assert await db.scalar(text('SELECT count(*) FROM automation_project_commands'))==3
    asyncio.run(scenario())
