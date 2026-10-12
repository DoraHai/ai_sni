"""Real scoped HTTP, project queue, worker and metering; synthetic local PG only."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import date
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text,select

from app import automation_projects as core, seo_automation_projects as automation
from app import seo_onsite_ai as ai, seo_onsite_ai_jobs as worker
from app.api import seo_automation_projects as api
from app.models.module_workspace import SeoSite,TenantModule
from app.models.seo import SeoSiteAdvisorAssignment
from app.models.seo_cockpit import SeoTask
from app.models.user import User
from app.models.role import Role
from app.security.auth import AuthContext
from test_seo_workflow_postgres import ADVISOR
from test_seo_onsite_ai_postgres import fixture,supplier,real_metered_supplier,install_guard_tables,guard_response

pytestmark=pytest.mark.skipif(not os.getenv('SEO_WORKFLOW_TEST_DATABASE_URL'),reason='isolated local PG required')
ROOT='/api/v1/seo/workbench/automation-projects'
KEY=core.scope('seo',4,2)


@asynccontextmanager
async def environment(*,install=True,readonly=False,ctx=ADVISOR):
    async with fixture() as (sessions,task):
        if install:
            async with sessions.begin() as db:
                raw=(await (await db.connection()).get_raw_connection()).driver_connection
                await raw.execute((Path(__file__).parents[1]/'scripts/automation_projects_schema.sql').read_text(encoding='utf-8'))
        app=FastAPI()
        app.include_router(api.router,prefix='/api/v1/seo')
        async def db_dep():
            async with sessions() as db:
                if readonly: await db.execute(text('SET TRANSACTION READ ONLY'))
                yield db
        app.dependency_overrides[api.get_seo_session]=db_dep
        app.dependency_overrides[api.require_seo_scoped_auth]=lambda:ctx
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://synthetic') as client:
            yield sessions,task,client


def configuration(task):
    return dict(task_ids=[task['id']],operations=['onsite_ai'],cycle={'mode':'daily','enabled':True},
        limits={'max_dispatches_per_run':1},stop_condition='drafts_ready_or_blocked',owner_user_id=7)


async def configure(client,task,**changes):
    response=await client.put(ROOT+'/2/control',json={'tenant_id':4,'request_id':str(uuid4()),
        'expected_version':0,'configuration':configuration(task),**changes})
    return response


async def action(client,project,verb):
    response=await client.post(ROOT+'/2/control',json={'tenant_id':4,'request_id':str(uuid4()),
        'expected_version':project['version'],'action':verb})
    assert response.status_code==200,response.text
    return response.json()


async def start(client,task):
    response=await configure(client,task)
    assert response.status_code==200,response.text
    return await action(client,response.json(),'start')


async def child(sessions,task):
    async with sessions() as db:
        row=await db.get(SeoTask,task['id'])
        key=row.params['onsite']['ai_run']['request_id']
        return key,deepcopy(row.params['onsite_ai_requests'][key])


def test_full_http_config_queue_worker_history_events_and_synthetic_samples(supplier):
    async def scenario():
        async with environment() as (sessions,task,client):
            off=await client.get(ROOT+'/2/control?tenant_id=4')
            assert off.status_code==200 and off.json()['state']=='not_started'
            project=await start(client,task)
            configured=await client.get(ROOT+'/2/events?tenant_id=4')
            assert configured.json()['items'][0]['run_id'] is None
            await automation.dispatch_project(KEY,sessions=sessions)
            key,_=await child(sessions,task)
            assert len(supplier)==0
            assert await worker.execute_request(task['id'],4,2,key,sessions=sessions)=='ready'
            assert len(supplier)==1
            run=await client.get(ROOT+f"/2/runs/{project['current_run_id']}?tenant_id=4")
            value=run.json()['run']
            assert value['state']=='waiting_human' and value['steps'][0]['status']=='succeeded'
            assert value['completion_evidence'] is None and value['steps'][0]['fee_state']=='unknown_charge'
            async with sessions() as db:
                row=await db.get(SeoTask,task['id'])
                assert row.params['onsite']['phase']=='review' and row.completion_evidence is None
            ended=await action(client,project,'end')
            assert ended['state']=='idle' and ended['current_run_id']==project['current_run_id']
            # Future cycles cannot regenerate an existing proposal or create tasks.
            async with sessions.begin() as db:
                await db.execute(text("UPDATE automation_projects SET next_due_at=CURRENT_TIMESTAMP - interval '1 second'"))
            await automation.dispatch_project(KEY,sessions=sessions)
            await automation.dispatch_project(KEY,sessions=sessions)
            latest=(await client.get(ROOT+'/2/control?tenant_id=4')).json()
            next_run=(await client.get(ROOT+f"/2/runs/{latest['current_run_id']}?tenant_id=4")).json()
            assert next_run['run']['state']=='waiting_input' and len(supplier)==1
            history=(await client.get(ROOT+'/2/runs?tenant_id=4&limit=1')).json()
            assert history['next_before_run_id']
            previous=(await client.get(ROOT+'/2/runs',params={'tenant_id':4,'before_run_id':history['next_before_run_id']})).json()
            assert previous['items'][0]['id']==project['current_run_id']
            sample={}
            for path in ['', '/2/control?tenant_id=4','/2/runs?tenant_id=4','/2/events?tenant_id=4',
                    f"/2/runs/{project['current_run_id']}?tenant_id=4",f"/2/runs/{project['current_run_id']}/events?tenant_id=4"]:
                response=await client.get(ROOT+path)
                assert response.status_code==200,response.text
                assert response.headers['cache-control']=='no-store'
                assert 'automation_token' not in response.text and 'provider_metadata' not in response.text
                sample[ROOT+path]=response.json()
            target=os.getenv('SEO_AUTOMATION_SAMPLE_PATH')
            if target:
                target=Path(target).resolve()
                assert target.is_relative_to(Path(os.environ['TEMP']).resolve())
                target.write_text(json.dumps({'source':'isolated synthetic PostgreSQL HTTP test; not production',
                    'responses':sample},ensure_ascii=False,indent=2),encoding='utf-8')
    asyncio.run(scenario())


@pytest.mark.parametrize('action_name',['pause','takeover','end'])
def test_inflight_control_with_real_fee_ledger_preserves_cost_but_no_business_write(monkeypatch,action_name):
    async def scenario():
        async with environment() as (sessions,task,client):
            sent=[]
            project=await start(client,task)
            async def provider(request):
                sent.append(request)
                stop=await action(client,project,action_name)
                assert stop['state']=={'pause':'pausing','takeover':'taking_over','end':'ending'}[action_name]
                return guard_response(request)
            real_metered_supplier(monkeypatch,sessions,provider)
            await install_guard_tables(sessions)
            await automation.dispatch_project(KEY,sessions=sessions)
            key,_=await child(sessions,task)
            assert await worker.execute_request(task['id'],4,2,key,sessions=sessions)=='stale'
            assert len(sent)==1
            response=await client.get(ROOT+'/2/control?tenant_id=4')
            assert response.json()['state']=={'pause':'paused','takeover':'taken_over','end':'idle'}[action_name]
            run=(await client.get(ROOT+f"/2/runs/{project['current_run_id']}?tenant_id=4")).json()['run']
            assert run['steps'][0]['status']=='stale' and run['steps'][0]['fee_state']=='recorded'
            assert any(ref.startswith('api_event:') for ref in run['steps'][0]['evidence_refs'])
            async with sessions() as db:
                row=await db.get(SeoTask,task['id'])
                assert row.params['onsite']['revision']==1 and row.params['onsite']['phase']=='draft'
                assert 'ai_proposal' not in row.params['onsite']
                assert await db.scalar(text('SELECT count(*) FROM api_usage_events'))==1
            assert await worker.execute_request(task['id'],4,2,key,sessions=sessions)=='stale'
            assert len(sent)==1
    asyncio.run(scenario())


@pytest.mark.parametrize('timing',['before_queue','before_provider'])
@pytest.mark.parametrize('change',['assignment','role','user','tenant','entitlement','site','task_scope'])
def test_live_permissions_and_scope_rechecked_before_actual_dispatch(supplier,timing,change):
    async def scenario():
        async with environment() as (sessions,task,client):
            project=await start(client,task)
            if timing=='before_provider':
                await automation.dispatch_project(KEY,sessions=sessions)
                request_id,_=await child(sessions,task)
            async with sessions.begin() as db:
                if change=='assignment': (await db.get(SeoSiteAdvisorAssignment,3)).active=False
                elif change=='role': (await db.get(Role,5)).permissions={'seo.site':'view','seo.content':'view'}
                elif change=='user': (await db.get(User,7)).is_active=False
                elif change=='tenant': (await db.get(User,7)).tenant_id=99
                elif change=='entitlement': (await db.get(TenantModule,1)).expires_at=date(2020,1,1)
                elif change=='site': (await db.get(SeoSite,2)).status='paused'
                elif change=='task_scope': (await db.get(SeoTask,task['id'])).site_id=999
            if timing=='before_queue': await automation.dispatch_project(KEY,sessions=sessions)
            else: await worker.execute_request(task['id'],4,2,request_id,sessions=sessions)
            if timing=='before_provider' and change=='task_scope':
                await automation.dispatch_project(KEY,sessions=sessions)
            assert len(supplier)==0
            async with sessions() as db:
                row=await db.get(SeoTask,task['id'])
                assert 'ai_proposal' not in row.params['onsite']
                run=await core.read_run(db,KEY,project['current_run_id'])
                assert run['steps'][0]['status'] in {'blocked','stale','unknown'}
                assert run['steps'][0]['fee_state']=='not_called'
    asyncio.run(scenario())


def test_pause_before_provider_cancel_reconcile_and_no_paid_replay(supplier):
    async def scenario():
        async with environment() as (sessions,task,client):
            project=await start(client,task)
            await automation.dispatch_project(KEY,sessions=sessions)
            key,_=await child(sessions,task)
            paused=await action(client,project,'pause')
            assert paused['state']=='pausing'
            assert await worker.execute_request(task['id'],4,2,key,sessions=sessions)=='stale'
            paused=(await client.get(ROOT+'/2/control?tenant_id=4')).json()
            assert paused['state']=='paused'
            resumed=await action(client,paused,'resume')
            await automation.dispatch_project(KEY,sessions=sessions)
            assert len(supplier)==0
            run=(await client.get(ROOT+f"/2/runs/{resumed['current_run_id']}?tenant_id=4")).json()['run']
            assert run['state']=='waiting_human' and run['dispatch_count']==1
    asyncio.run(scenario())


@pytest.mark.parametrize('install',[True,False])
def test_read_only_postgres_reads_no_initialization_and_pending_schema(install):
    async def scenario():
        async with environment(install=install,readonly=True) as (sessions,task,client):
            for path in ['', '/2/control?tenant_id=4']:
                response=await client.get(ROOT+path)
                assert response.status_code==200,response.text
                project=response.json() if path else response.json()['items'][0]
                assert project['state']==('not_started' if install else 'schema_pending')
                assert project['capabilities']['can_configure']==install
            for path in ['/2/events?tenant_id=4','/2/runs?tenant_id=4']:
                response=await client.get(ROOT+path)
                assert response.status_code==(200 if install else 503)
            if not install:
                response=await configure(client,task)
                assert response.status_code==503
                assert response.json()['detail']['code']=='automation_schema_pending'
    asyncio.run(scenario())


@pytest.mark.parametrize('ctx',[AuthContext(None,'','',None,{'*':'edit'}),AuthContext(7,'','',99,{})])
def test_http_rejects_api_key_and_foreign_tenant_context(ctx):
    async def scenario():
        async with environment(ctx=ctx) as (_,task,client):
            response=await configure(client,task)
            assert response.status_code==403
            assert response.headers['cache-control']=='no-store'
    asyncio.run(scenario())


@pytest.mark.parametrize('stage',['queue','provider'])
def test_logging_failure_never_calls_provider_and_rolls_back_admission(supplier,stage):
    async def scenario():
        async with environment() as (sessions,task,client):
            await start(client,task)
            if stage=='provider':
                await automation.dispatch_project(KEY,sessions=sessions)
                key,_=await child(sessions,task)
            async with sessions.begin() as db:
                await db.execute(text("CREATE FUNCTION fail_log() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic log failure'; END $$"))
                await db.execute(text('CREATE TRIGGER fail_log BEFORE INSERT ON automation_project_events FOR EACH ROW EXECUTE FUNCTION fail_log()'))
            with pytest.raises(Exception,match='synthetic log failure'):
                if stage=='queue': await automation.dispatch_project(KEY,sessions=sessions)
                else: await worker.execute_request(task['id'],4,2,key,sessions=sessions)
            assert len(supplier)==0
            async with sessions() as db:
                row=await db.get(SeoTask,task['id'])
                if stage=='queue':
                    assert not row.params.get('onsite_ai_requests')
                    assert 'onsite_ai_quota' not in (await db.get(SeoSite,2)).site_settings
                else: assert row.params['onsite_ai_requests'][key]['state']=='queued'
    asyncio.run(scenario())


def test_real_jwt_authentication_live_role_and_client_scope_selector(monkeypatch):
    from app.security import auth
    from app.database import get_session
    from app import config,seo_demo_source
    settings=config.get_settings().model_copy(update={'jwt_secret':'synthetic-automation-test-signing-secret',
        'seo_demo_mode':False,'seo_demo_data_source_enabled':False})
    monkeypatch.setattr(auth,'get_settings',lambda:settings)
    monkeypatch.setattr(seo_demo_source,'get_settings',lambda:settings)
    async def scenario():
        async with environment() as (sessions,task,_):
            app=FastAPI()
            app.include_router(api.router,prefix='/api/v1/seo')
            async def db_dep():
                async with sessions() as db: yield db
            app.dependency_overrides[get_session]=db_dep  # DB target only, real auth dependencies
            async with sessions() as db: token=auth.issue_token(await db.get(User,7))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://synthetic') as client:
                response=await client.get(ROOT+'/2/control?tenant_id=4')
                assert response.status_code==401
                assert response.headers['cache-control']=='no-store'
                client.headers['Authorization']='Bearer '+token
                response=await configure(client,task)
                assert response.status_code==200,response.text
                response=await client.get(ROOT+'/2/control?tenant_id=5')
                assert response.status_code in {403,404}
                response=await client.get(ROOT+'/2/control?tenant_id=4&data_source=primary')
                assert response.status_code==400
                async with sessions.begin() as db:
                    (await db.get(Role,5)).permissions={'seo.site':'view','seo.content':'view'}
                response=await client.get(ROOT+'/2/control?tenant_id=4')
                assert response.status_code==403  # unchanged JWT, live role changed
                client.headers['Authorization']='Bearer malformed-synthetic-token'
                assert (await client.get(ROOT)).status_code==401
    asyncio.run(scenario())


def test_http_scope_pagination_run_isolation_and_validation(supplier):
    async def scenario():
        async with environment() as (sessions,task,client):
            project=await start(client,task)
            async with sessions.begin() as db:
                for ident in (3,99):
                    db.add(SeoSite(id=ident,tenant_id=4,tenant_module_id=1,name=f'Synthetic {ident}',
                        domain=f'site{ident}.invalid',canonical_domain=f'site{ident}.invalid',status='active',site_settings={}))
                db.add(SeoSiteAdvisorAssignment(id=4,tenant_id=4,site_id=3,advisor_user_id=7,active=True))
            page=(await client.get(ROOT+'?limit=1')).json()
            assert page['items'][0]['scope_id']==3 and page['next_before_scope_id']==3
            assert 'total' not in page
            page=(await client.get(ROOT+'?limit=1&before_scope_id=3')).json()
            assert page['items'][0]['scope_id']==2 and page['next_before_scope_id'] is None
            for tail in [f"runs/{project['current_run_id']}",f"runs/{project['current_run_id']}/events",
                         f"runs?before_run_id={project['current_run_id']}"]:
                sep='&' if '?' in tail else '?'
                response=await client.get(ROOT+'/3/'+tail+sep+'tenant_id=4')
                assert response.status_code==404,response.text
            assert (await client.get(ROOT+'/99/control?tenant_id=4')).status_code==403
            for change in [{'tenant_id':4.0},{'configuration':{**configuration(task),'operations':['publish']}},
                           {'configuration':{**configuration(task),'owner_user_id':8}}]:
                response=await configure(client,task,**change)
                assert response.status_code in {409,422,403}
                assert response.headers['cache-control']=='no-store'
            assert len(supplier)==0
    asyncio.run(scenario())


def test_managed_worker_process_loss_preserves_ledger_and_never_repeats(monkeypatch):
    class ProcessLost(BaseException): pass
    async def scenario():
        async with environment() as (sessions,task,client):
            project=await start(client,task)
            sent=[]
            async def provider(request):
                sent.append(request)
                return guard_response(request)
            real_metered_supplier(monkeypatch,sessions,provider)
            await install_guard_tables(sessions)
            original=ai.generate
            async def lost(*args,**kwargs):
                await original(*args,**kwargs)
                raise ProcessLost()
            monkeypatch.setattr(ai,'generate',lost)
            await automation.dispatch_project(KEY,sessions=sessions)
            key,_=await child(sessions,task)
            with pytest.raises(ProcessLost): await worker.execute_request(task['id'],4,2,key,sessions=sessions)
            async with sessions.begin() as db:
                row=await db.get(SeoTask,task['id'])
                requests=deepcopy(row.params['onsite_ai_requests'])
                requests[key]['started_at']='2000-01-01T00:00:00'
                row.params={**row.params,'onsite_ai_requests':requests}
            assert await worker.execute_request(task['id'],4,2,key,sessions=sessions)=='unknown'
            assert await worker.execute_request(task['id'],4,2,key,sessions=sessions)=='unknown'
            await automation.dispatch_project(KEY,sessions=sessions)
            assert len(sent)==1
            run=(await client.get(ROOT+f"/2/runs/{project['current_run_id']}?tenant_id=4")).json()['run']
            assert run['steps'][0]['status']=='unknown' and run['steps'][0]['fee_state']=='recorded'
            assert run['state']=='waiting_human'
    asyncio.run(scenario())


def test_manual_cancel_during_provider_records_late_real_fee_without_adoption(monkeypatch):
    from app.api import seo_onsite_ai as queue
    async def scenario():
        async with environment() as (sessions,task,client):
            project=await start(client,task)
            async def provider(request):
                async with sessions() as db:
                    await queue.cancel_proposal(task['id'],request_id,queue.RunScope(tenant_id=4,site_id=2),db,ADVISOR)
                await automation.dispatch_project(KEY,sessions=sessions)
                return guard_response(request)
            real_metered_supplier(monkeypatch,sessions,provider)
            await install_guard_tables(sessions)
            await automation.dispatch_project(KEY,sessions=sessions)
            request_id,_=await child(sessions,task)
            assert await worker.execute_request(task['id'],4,2,request_id,sessions=sessions)=='unknown'
            page=(await client.get(ROOT+'/2/events?tenant_id=4')).json()
            receipt=[e for e in page['items'] if e['code']=='late_provider_receipt']
            assert len(receipt)==1 and receipt[0]['fee_state']=='recorded'
            async with sessions() as db:
                assert (await db.get(SeoTask,task['id'])).params['onsite']['revision']==1
                assert await db.scalar(text('SELECT count(*) FROM api_usage_events'))==1
    asyncio.run(scenario())


def test_inflight_project_marker_removal_cannot_downgrade_fence(monkeypatch,supplier):
    async def scenario():
        async with environment() as (sessions,task,client):
            project=await start(client,task)
            await automation.dispatch_project(KEY,sessions=sessions)
            request_id,_=await child(sessions,task)
            original=ai.generate
            async def changed(*args,**kwargs):
                await action(client,project,'pause')
                async with sessions.begin() as db:
                    row=await db.get(SeoTask,task['id'])
                    requests=deepcopy(row.params['onsite_ai_requests'])
                    requests[request_id].pop('automation_token')
                    row.params={**row.params,'onsite_ai_requests':requests}
                return await original(*args,**kwargs)
            monkeypatch.setattr(ai,'generate',changed)
            assert await worker.execute_request(task['id'],4,2,request_id,sessions=sessions)=='stale'
            assert len(supplier)==1
            async with sessions() as db:
                assert (await db.get(SeoTask,task['id'])).params['onsite']['revision']==1
                assert (await core.read_project(db,KEY))['state']=='paused'
    asyncio.run(scenario())


def test_database_failure_is_sanitized_and_never_looks_like_empty_project(monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    async def scenario():
        async with environment() as (_,task,client):
            async def unavailable(db): raise SQLAlchemyError('private database address and password')
            monkeypatch.setattr(core,'schema_ready',unavailable)
            response=await client.get(ROOT+'/2/control?tenant_id=4')
            assert response.status_code==503
            assert response.headers['cache-control']=='no-store'
            assert response.json()['detail']['code']=='automation_unavailable'
            assert 'private' not in response.text and 'password' not in response.text
    asyncio.run(scenario())


def test_queued_project_marker_removal_does_not_bypass_pause(supplier):
    async def scenario():
        async with environment() as (sessions,task,client):
            project=await start(client,task)
            await automation.dispatch_project(KEY,sessions=sessions)
            request_id,_=await child(sessions,task)
            await action(client,project,'pause')
            async with sessions.begin() as db:
                row=await db.get(SeoTask,task['id'])
                requests=deepcopy(row.params['onsite_ai_requests'])
                requests[request_id].pop('automation_token')
                row.params={**row.params,'onsite_ai_requests':requests}
            assert await worker.execute_request(task['id'],4,2,request_id,sessions=sessions)=='stale'
            assert len(supplier)==0
            async with sessions() as db:
                assert (await core.read_project(db,KEY))['state']=='paused'
    asyncio.run(scenario())


def test_scheduler_waiting_human_projects_do_not_starve_next_queue(monkeypatch):
    from app.automation_project_contract import Configure,Control
    async def scenario():
        async with environment() as (sessions,task,client):
            async with sessions.begin() as db:
                for ident in range(100,122):
                    key=core.scope('seo',4,ident)
                    saved,_,_=await core.configure_project(db,key,Configure(tenant_id=4,request_id=uuid4(),
                        expected_version=0,configuration=configuration(task)),7)
                    await core.control_project(db,key,Control(tenant_id=4,request_id=uuid4(),expected_version=saved['version'],action='start'),7)
                await db.execute(text("UPDATE automation_project_runs SET state='waiting_human' WHERE scope_id<121"))
            seen=[]
            async def dispatch(key,**kwargs): seen.append(key)
            monkeypatch.setattr(automation,'dispatch_project',dispatch)
            await automation.run_automation_projects(sessions=sessions)
            assert seen==[core.scope('seo',4,121)]
    asyncio.run(scenario())


def test_durable_dispatch_marker_prevents_false_not_called_when_child_timestamp_missing():
    async def scenario():
        async with environment() as (sessions,task,client):
            await start(client,task)
            await automation.dispatch_project(KEY,sessions=sessions)
            _,request=await child(sessions,task)
            token=request['automation_token']
            async with sessions.begin() as db:
                assert (await automation.fee_evidence(db,token,request))[0]=='not_called'
                assert await core.begin_dispatch(db,token)
            async with sessions() as db:
                assert request['started_at'] is None
                assert (await automation.fee_evidence(db,token,request))[0]=='unknown_charge'
    asyncio.run(scenario())


def test_reconciliation_never_follows_child_token_into_other_scope(supplier):
    async def scenario():
        async with environment() as (sessions,task,client):
            project=await start(client,task)
            await automation.dispatch_project(KEY,sessions=sessions)
            request_id,_=await child(sessions,task)
            async with sessions.begin() as db:
                row=await db.get(SeoTask,task['id'])
                requests=deepcopy(row.params['onsite_ai_requests'])
                requests[request_id]['automation_token']['module']='geo'
                requests[request_id]['automation_token']['tenant_id']=999
                row.params={**row.params,'onsite_ai_requests':requests}
            await automation.dispatch_project(KEY,sessions=sessions)
            async with sessions() as db:
                run=await core.read_run(db,KEY,project['current_run_id'])
                assert run['steps'][0]['status']=='unknown'
                assert await db.scalar(text("SELECT count(*) FROM automation_project_events WHERE module<>'seo' OR tenant_id<>4"))==0
            assert len(supplier)==0
    asyncio.run(scenario())
