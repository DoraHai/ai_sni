"""Real JWT/HTTP and isolated PG; every provider is synthetic."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import text,select
from sqlalchemy.schema import CreateTable
from sqlalchemy.exc import SQLAlchemyError

from app import automation_projects as core, seo_automation_projects as automation
from app import seo_onsite_ai_jobs as worker, seo_onsite_ai as ai
from app.api import seo_automation_projects as api, seo_onsite_ai as queue
from app.models.user import User
from app.models.role import Role
from app.models.module_workspace import SeoSite
from app.models.seo_cockpit import SeoTask
from app.security import auth
from app.database import get_session
from test_seo_onsite_ai_postgres import fixture, supplier
from test_seo_automation_projects_postgres import ROOT, KEY, action, child

pytestmark=pytest.mark.skipif(not os.getenv('SEO_WORKFLOW_TEST_DATABASE_URL'),reason='isolated local PG required')
HEALTH='/api/v1/seo/workbench/automation-health'
SAMPLES={'responses':{},'scenarios':[]}


async def record_response(response):
    await response.aread()
    if 'application/json' not in response.headers.get('content-type',''): return
    path=response.request.url.raw_path.decode('ascii')
    value={'status':response.status_code,'headers':{k:response.headers[k] for k in
        ('cache-control','content-type','x-snapshot-upper-id','x-next-after-id') if k in response.headers},'body':response.json()}
    if response.request.method=='GET': SAMPLES['responses'][path]=value
    SAMPLES['scenarios'].append({'case':os.getenv('PYTEST_CURRENT_TEST','').split(' ')[0],
        'method':response.request.method,'path':path,**value})


def save_samples():
    root=Path(__file__).parents[1]
    data={'source':'isolated PostgreSQL + real JWT + ASGI HTTP; synthetic records and mocked providers only',
        'backend_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
        'source_tree_clean':not bool(subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip()),**SAMPLES}
    (Path(os.environ['TEMP'])/'seo-automation-v2-http-samples.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


@asynccontextmanager
async def environment(*,install=True,readonly=False):
    async with fixture() as (sessions,task):
        if install:
            async with sessions.begin() as db:
                raw=(await (await db.connection()).get_raw_connection()).driver_connection
                for name in ('automation_projects_schema.sql','automation_projects_v2_schema.sql'):
                    await raw.execute((Path(__file__).parents[1]/'scripts'/name).read_text(encoding='utf-8'))
            await sessions.kw['bind'].dispose()
        app=FastAPI()
        app.include_router(api.router,prefix='/api/v1/seo')
        app.include_router(api.health_router,prefix='/api/v1/seo')
        async def db_dep():
            async with sessions() as db:
                if readonly: await db.execute(text('SET TRANSACTION READ ONLY'))
                yield db
        app.dependency_overrides[get_session]=db_dep
        async with sessions() as db:
            token=auth.issue_token(await db.get(User,7))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://synthetic',
                headers={'Authorization':'Bearer '+token},event_hooks={'response':[record_response]}) as client:
            try: yield sessions,task,client
            finally: save_samples()


async def configure(client,operation='onsite_ai'):
    response=await client.get(ROOT+'/2/configuration-basis?tenant_id=4&operation='+operation)
    assert response.status_code==200,response.text
    basis=response.json()
    config={'contract_version':2,'operations':[operation],
        'targets':[{k:v for k,v in t.items() if k!='label'} for t in basis['targets'][:1]],
        'service_plan':basis['service_plan'],'source_bindings':basis['source_bindings'],
        'cycle':{'mode':'once','enabled':False},
        'limits':{'max_dispatches_per_run':1,'max_external_calls_per_run':10 if operation in {'site_diagnosis','incremental_diagnosis'} else 1},
        'stop_condition':'drafts_ready_or_blocked','owner_user_id':7}
    response=await client.put(ROOT+'/2/control',json={'tenant_id':4,'request_id':str(uuid4()),
        'expected_version':0,'configuration':config})
    assert response.status_code==200,response.text
    return response.json(),basis


def test_v2_actual_http_lifecycle_receipts_export_and_samples(supplier):
    async def scenario():
        async with environment() as (sessions,task,client):
            project,basis=await configure(client)
            project=await action(client,project,'start')
            await automation.dispatch_project(KEY,sessions=sessions)
            request_id,_=await child(sessions,task)
            assert await worker.execute_request(task['id'],4,2,request_id,sessions=sessions)=='ready'
            assert await worker.execute_request(task['id'],4,2,request_id,sessions=sessions)=='ready'
            assert len(supplier)==1
            run=(await client.get(ROOT+f"/2/runs/{project['current_run_id']}?tenant_id=4")).json()
            assert run['run']['steps'][0]['calls'][0]['state']=='succeeded'
            assert run['run']['steps'][0]['fee_state']=='unknown_charge'  # mock lacks real ledger receipt
            first=(await client.get(ROOT+'/2/events/export?tenant_id=4&limit=1')).json()
            assert len(first['items'])==1 and first['items'][0]['safe_changes']
            ended=await action(client,project,'end_project')
            assert ended['ended_at'] and not ended['cycle_enabled']
            for path in ('/2/control?tenant_id=4','/2/runs?tenant_id=4','/2/events?tenant_id=4','?tenant_id=4'):
                response=await client.get(ROOT+path)
                assert response.status_code==200,response.text
            page=await client.get(ROOT+f"/2/events/export?tenant_id=4&through_id={first['snapshot_upper_id']}")
            assert max(e['id'] for e in page.json()['items'])<=first['snapshot_upper_id']
            csv=await client.get(ROOT+'/2/events/export?tenant_id=4&format=csv')
            assert csv.status_code==200 and csv.headers['x-snapshot-upper-id']
            assert csv.headers['cache-control']=='no-store'
            async with sessions.begin() as db:
                role=await db.get(Role,5)
                role.permissions={**role.permissions,'settings.accounts':'edit','settings.customers':'edit'}
            health=await client.get(HEALTH)
            assert health.status_code==200 and health.json()['counts']['unknown_cost']==1
            assert health.json()['overall']=='unverified'
    asyncio.run(scenario())


def test_interrupted_provider_claim_is_unknown_and_never_redispatched(monkeypatch):
    from datetime import timedelta
    from app import automation_project_v2 as v2, seo_automation_execution as execution
    async def scenario():
        async with environment() as (sessions,task,client):
            project,_=await configure(client,'ranking_collect')
            project=await action(client,project,'start')
            async with sessions.begin() as db:
                token=await core.claim_step(db,KEY)
                assert await v2.begin_call(db,token,'interrupted')
            async def forbidden(*args,**kwargs):
                pytest.fail('An admitted interrupted step must never execute again')
            monkeypatch.setattr(execution,'execute',forbidden)
            await automation.dispatch_project(KEY,sessions=sessions)
            async with sessions() as db:
                run=await core.read_run(db,KEY,project['current_run_id'])
                assert run['steps'][0]['status']=='running'
            later=core.now()+timedelta(seconds=181)
            monkeypatch.setattr(core,'now',lambda:later)
            await automation.dispatch_project(KEY,sessions=sessions)
            await automation.dispatch_project(KEY,sessions=sessions)
            async with sessions() as db:
                run=await core.read_run(db,KEY,project['current_run_id'])
                step=run['steps'][0]
                assert step['status']=='unknown' and run['dispatch_count']==1
                assert len(step['calls'])==1 and step['calls'][0]['state']=='unknown'
                assert step['fee_state']=='unknown_charge'
    asyncio.run(scenario())


@pytest.mark.parametrize('case',['success','pause_during_call','provider_timeout','log_failure'])
def test_real_rank_collector_individual_call_receipt_and_stop(case,monkeypatch):
    from app import seo_serp, seo_automation_boundary as boundary
    from app.api import seo as seo_api
    from app.models.seo import SeoRankSnapshot,SeoMetricSnapshot,SeoSerpResult
    async def scenario():
        async with environment() as (sessions,task,client):
            async with sessions.begin() as db:
                for model in (SeoRankSnapshot,SeoMetricSnapshot,SeoSerpResult):
                    await db.execute(CreateTable(model.__table__,include_foreign_key_constraints=[]))
            settings=seo_serp.get_settings().model_copy(update={'chinaz_api_enabled':True,
                'chinaz_baidu_pc_ranking_api_key':'synthetic-never-sent','chinaz_api_base_url':'https://synthetic.invalid'})
            monkeypatch.setattr(seo_serp,'get_settings',lambda:settings)
            monkeypatch.setattr(boundary,'async_session_factory',sessions)
            project,_=await configure(client,'ranking_collect')
            project=await action(client,project,'start')
            calls=[]
            async def send(*args,**kwargs):
                calls.append(1)
                if case=='pause_during_call': await action(client,project,'pause')
                if case=='provider_timeout': raise httpx.ReadTimeout('synthetic timeout')
                return httpx.Response(200,json={'StateCode':1,'Result':{'Ranks':[
                    {'RankStr':'1-3','Url':'https://example.com/p','Title':'公开事实'}]}},
                    request=httpx.Request('GET','https://synthetic.invalid'))
            monkeypatch.setattr(seo_serp,'metered_request',send)
            if case=='log_failure':
                original=core.append_event
                async def fail(db,key,**kwargs):
                    if kwargs['code']=='external_call_admitted': raise SQLAlchemyError('synthetic log unavailable')
                    return await original(db,key,**kwargs)
                monkeypatch.setattr(core,'append_event',fail)
            await automation.dispatch_project(KEY,sessions=sessions)
            await automation.dispatch_project(KEY,sessions=sessions)
            assert len(calls)==(0 if case=='log_failure' else 1)
            async with sessions() as db:
                count=await db.scalar(text('SELECT count(*) FROM seo_rank_snapshots'))
                assert count==(1 if case=='success' else 0)
                run=await core.read_run(db,KEY,project['current_run_id'])
                assert run['steps'][0]['status']==('succeeded' if case=='success' else 'stale' if case=='pause_during_call' else 'unknown' if case=='provider_timeout' else 'blocked')
                if calls:
                    assert len(run['steps'][0]['calls'])==1
                    assert run['steps'][0]['fee_state']=='unknown_charge'
            # The old scheduler cannot re-enter adopted operations, even after stop.
            with boundary.use(boundary.Boundary(KEY,'ranking_collect',sessions=sessions)):
                with pytest.raises(HTTPException):
                    await boundary.provider_call(send,None,'get','https://synthetic.invalid')
            assert len(calls)==(0 if case=='log_failure' else 1)
    asyncio.run(scenario())


@pytest.mark.parametrize('timing',['before_dispatch','before_call','during_call'])
def test_v2_plan_change_fences_queue_provider_and_result(timing,monkeypatch,supplier):
    async def scenario():
        async with environment() as (sessions,task,client):
            project,_=await configure(client)
            project=await action(client,project,'start')
            async def changed():
                async with sessions.begin() as db:
                    site=await db.get(SeoSite,2)
                    settings=deepcopy(site.site_settings)
                    settings['seo_service_plan']['optimization_directions']=['changed without bump']
                    site.site_settings=settings
            if timing=='before_dispatch':
                await changed()
                await automation.dispatch_project(KEY,sessions=sessions)
            else:
                await automation.dispatch_project(KEY,sessions=sessions)
                request_id,_=await child(sessions,task)
                if timing=='before_call': await changed()
                else:
                    original=ai.generate
                    async def generate(*args,**kwargs):
                        await changed()
                        return await original(*args,**kwargs)
                    monkeypatch.setattr(ai,'generate',generate)
                assert await worker.execute_request(task['id'],4,2,request_id,sessions=sessions)=='stale'
            assert len(supplier)==(1 if timing=='during_call' else 0)
            async with sessions() as db:
                assert 'ai_proposal' not in (await db.get(SeoTask,task['id'])).params['onsite']
                run=await core.read_run(db,KEY,project['current_run_id'])
                assert run['steps'][0]['status'] in {'blocked','stale'}
    asyncio.run(scenario())


@pytest.mark.parametrize('case',['advisor','one_permission','tenant','inactive','api_key','anonymous'])
def test_health_rejects_non_global_named_live_two_permission_identity(case):
    async def scenario():
        async with environment() as (sessions,task,client):
            async with sessions.begin() as db:
                role=await db.get(Role,5)
                if case!='advisor': role.permissions={'settings.accounts':'edit','settings.customers':'edit'}
                if case=='one_permission': role.permissions={'settings.accounts':'edit'}
                if case=='tenant': (await db.get(User,7)).tenant_id=4
                if case=='inactive': (await db.get(User,7)).is_active=False
            if case in {'api_key','anonymous'}:
                client.headers.pop('Authorization')
                if case=='api_key': client.headers['X-API-Key']=auth.get_settings().admin_api_key
            response=await client.get(HEALTH)
            assert response.status_code in {401,403},response.text
    asyncio.run(scenario())


def test_readonly_missing_schema_scope_and_database_failure(monkeypatch):
    async def scenario():
        async with environment(install=False,readonly=True) as (sessions,task,client):
            result=await client.get(ROOT+'/2/configuration-basis?tenant_id=4&operation=onsite_ai')
            assert result.status_code==200 and result.json()['state']=='schema_pending'
            assert result.json()['targets']==[]
            denied=await client.get(ROOT+'/2/configuration-basis?tenant_id=99&operation=onsite_ai')
            assert denied.status_code in {403,404}
            async with sessions.begin() as db:
                (await db.get(Role,5)).permissions={'settings.accounts':'edit','settings.customers':'edit'}
            health=await client.get(HEALTH)
            assert health.json()['state']=='schema_pending'
            assert all(v is None for v in health.json()['counts'].values())
            async def broken(*args,**kwargs): raise SQLAlchemyError('private database password')
            monkeypatch.setattr(api.v2,'health_snapshot',broken)
            health=await client.get(HEALTH)
            assert health.status_code==503 and health.json()['state']=='unavailable'
            assert 'password' not in health.text
    asyncio.run(scenario())


@pytest.mark.parametrize('case',['success','paused','missing_provider','cached'])
def test_domain_indexation_reuses_real_parser_and_scoped_metric(case,monkeypatch):
    from app import seo_chinaz
    from app.geo import chinaz
    from app.models.seo import SeoMetricSnapshot
    async def scenario():
        async with environment() as (sessions,task,client):
            async with sessions.begin() as db:
                await db.execute(CreateTable(SeoMetricSnapshot.__table__,include_foreign_key_constraints=[]))
            settings=chinaz.get_settings().model_copy(update={'chinaz_api_enabled':case!='missing_provider',
                'chinaz_api_key':'synthetic-not-real','chinaz_baidu_index_api_key':'synthetic-not-real',
                'chinaz_api_base_url':'https://synthetic.invalid'})
            monkeypatch.setattr(chinaz,'get_settings',lambda:settings)
            chinaz._baidu_index_cache.clear()
            project,_=await configure(client,'indexation_collection')
            project=await action(client,project,'start')
            calls=[]
            async def send(request):
                calls.append(1)
                if case=='paused': await action(client,project,'pause')
                return httpx.Response(200,json={'StateCode':1,'Result':{'SiteCount':17}})
            original=seo_chinaz.GuardedClient.__init__
            def init(self,**kwargs): original(self,transport=httpx.MockTransport(send),**kwargs)
            monkeypatch.setattr(seo_chinaz.GuardedClient,'__init__',init)
            if case=='cached':
                value=chinaz._parse_baidu_index_response({'StateCode':1,'Result':{'SiteCount':17}},'example.com')
                chinaz._cache_put(chinaz._baidu_index_cache,'example.com',value)
            await automation.dispatch_project(KEY,sessions=sessions)
            async with sessions() as db:
                rows=list((await db.execute(text('SELECT * FROM seo_metric_snapshots'))).mappings())
                assert len(rows)==(0 if case=='paused' else 1)
                if rows:
                    assert rows[0]['data_quality']=='estimated'
                    if case=='missing_provider': assert rows[0]['numeric_value'] is None
                    else:
                        assert rows[0]['numeric_value']==17
                        assert '不等同' in rows[0]['raw_payload']['methodology']
                run=await core.read_run(db,KEY,project['current_run_id'])
                assert run['steps'][0]['status']==('stale' if case=='paused' else 'blocked' if case=='missing_provider' else 'succeeded')
            assert len(calls)==(0 if case in {'missing_provider','cached'} else 1)
            chinaz._baidu_index_cache.clear()
    asyncio.run(scenario())


def test_basis_filters_busy_rows_before_pagination():
    async def scenario():
        async with environment() as (sessions,task,client):
            async with sessions.begin() as db:
                original=await db.get(SeoTask,task['id'])
                for ident in (100,101,102,103):
                    params=deepcopy(original.params)
                    if ident in (101,103): params['onsite_ai_requests']={'old':{'state':'running'}}
                    db.add(SeoTask(id=ident,tenant_id=4,site_id=2,module='seo',action_type=original.action_type,
                        title='synthetic pagination',params=params,status='open',created_by='7',assignee_role='seo_advisor'))
            one=(await client.get(ROOT+'/2/configuration-basis?tenant_id=4&operation=onsite_ai&limit=1')).json()
            assert [t['object_id'] for t in one['targets']]==[102]
            assert one['next_before_object_id']==102
            two=(await client.get(ROOT+'/2/configuration-basis?tenant_id=4&operation=onsite_ai&limit=1&before_object_id=102')).json()
            assert [t['object_id'] for t in two['targets']]==[100]
            assert two['next_before_object_id']==100
    asyncio.run(scenario())


@pytest.mark.parametrize('case',['success','paused','bad_answer'])
def test_content_uses_existing_draft_quota_and_manual_review_boundary(case,monkeypatch):
    from app import seo_content_drafting as drafts,seo_ai_operations as ops,seo_content_workflow as flow
    from app.api import seo as seo_api
    from app.models.seo import SeoContentAsset
    async def scenario():
        async with environment() as (sessions,task,client):
            monkeypatch.setattr(ops,'async_session_factory',sessions)
            monkeypatch.setattr(flow,'async_session_factory',sessions)
            monkeypatch.setattr(seo_api,'is_enabled',lambda:True)
            settings=seo_api.get_settings().model_copy(update={'deepseek_api_key':'synthetic-not-real',
                'deepseek_base_url':'https://api.deepseek.com','seo_ai_max_requests_per_tenant_per_day':5})
            monkeypatch.setattr(seo_api,'get_settings',lambda:settings)
            async with sessions.begin() as db:
                site=await db.get(SeoSite,2)
                site.site_settings={'seo_service_plan':{**site.site_settings['seo_service_plan'],
                    'content_ai_enabled':True,'content_ai_authorized_by':7,'content_ai_fact_ids':[30],
                    'content_ai_keyword_ids':[20]}}
            project,_=await configure(client,'content_draft')
            project=await action(client,project,'start')
            calls=[]
            async def provider(*args,**kwargs):
                calls.append(1)
                if case=='paused': await action(client,project,'pause')
                return {} if case=='bad_answer' else {'title':'selection','outline':'Guidance',
                    'content':'selection: Read official guidance.[F30]'}
            monkeypatch.setattr(seo_api,'chat_json',provider)
            await automation.dispatch_project(KEY,sessions=sessions)
            assert len(calls)==1
            async with sessions() as db:
                row=await db.scalar(select(SeoContentAsset))
                assert row.status==('drafting' if case=='success' else 'planned')
                assert row.reviewed_by is None and row.published_at is None
                if case!='success': assert not row.draft
                run=await core.read_run(db,KEY,project['current_run_id'])
                assert run['steps'][0]['status']==('succeeded' if case=='success' else 'stale' if case=='paused' else 'blocked')
                assert len(run['steps'][0]['calls'])==1
                draft_task=await db.scalar(select(SeoTask).where(SeoTask.action_type=='content_delivery'))
                ident=draft_task.id
            # Neither the old cycle nor restart recovery is allowed to relaunch it.
            await flow.process_site(2)
            with pytest.raises(HTTPException): await drafts.execute_content_draft(ident,sessions=sessions)
            assert len(calls)==1
    asyncio.run(scenario())


@pytest.mark.parametrize('operation',['site_diagnosis','incremental_diagnosis'])
@pytest.mark.parametrize('paused',[False,True])
def test_crawler_individual_http_gate_and_actual_snapshot(operation,paused,monkeypatch):
    from app import seo_crawler as crawler,seo_service_workflows as service
    from app.models.seo import SeoPageSnapshot,SeoCrawlRun,SeoRankSnapshot
    from app.models.seo_site_analytics import SeoSiteAnalyticsSource,SeoSiteAnalyticsMonthly
    async def scenario():
        async with environment() as (sessions,task,client):
            async with sessions.begin() as db:
                for model in (SeoPageSnapshot,SeoCrawlRun,SeoRankSnapshot,SeoSiteAnalyticsSource,SeoSiteAnalyticsMonthly):
                    await db.execute(CreateTable(model.__table__,include_foreign_key_constraints=[]))
                site=await db.get(SeoSite,2)
                site.site_settings={'seo_service_plan':{**site.site_settings['seo_service_plan'],
                    'website_incremental_enabled':True,'website_max_pages':1}}
            project,_=await configure(client,operation)
            project=await action(client,project,'start')
            calls=[]
            class Transport(crawler.PinnedAsyncHTTPTransport):
                async def handle_async_request(self,request):
                    calls.append(request.url.path)
                    if paused and len(calls)==1: await action(client,project,'pause')
                    if request.url.path=='/robots.txt':
                        return httpx.Response(200,text='User-agent: *\nAllow: /\nSitemap: https://example.com/sitemap.xml',headers={'content-type':'text/plain'},request=request)
                    if request.url.path.endswith('.xml'):
                        return httpx.Response(200,text='<urlset><url><loc>https://example.com/p</loc></url></urlset>',headers={'content-type':'application/xml'},request=request)
                    return httpx.Response(200,text='<html><head><title>事实标题</title></head><body>公开说明</body></html>',headers={'content-type':'text/html'},request=request)
            async def public(url): return '93.184.216.34'
            monkeypatch.setattr(crawler,'_ensure_public_host',public)
            monkeypatch.setattr(crawler,'pinned_async_client',lambda **kwargs:httpx.AsyncClient(transport=Transport(),**kwargs))
            await automation.dispatch_project(KEY,sessions=sessions)
            async with sessions() as db:
                count=await db.scalar(text('SELECT count(*) FROM seo_page_snapshots'))
                assert count==(0 if paused else 1)
                run=await core.read_run(db,KEY,project['current_run_id'])
                assert run['steps'][0]['status']==('stale' if paused else 'succeeded')
                assert len(run['steps'][0]['calls'])==len(calls)
                assert all(c['kind']=='http' and c['fee_state']=='not_called' for c in run['steps'][0]['calls'])
            assert len(calls)==(1 if paused else 2 if operation=='site_diagnosis' else 4)
    asyncio.run(scenario())


@pytest.mark.parametrize('operation',['monthly_onsite_plan','monthly_report'])
def test_monthly_drafts_are_real_records_without_automatic_acceptance(operation):
    from app.models.seo_site_analytics import SeoSiteAnalyticsSource,SeoSiteAnalyticsMonthly
    async def scenario():
        async with environment() as (sessions,task,client):
            async with sessions.begin() as db:
                if operation=='monthly_report':
                    for model in (SeoSiteAnalyticsSource,SeoSiteAnalyticsMonthly):
                        await db.execute(CreateTable(model.__table__,include_foreign_key_constraints=[]))
                    db.add(SeoTask(id=200,tenant_id=4,site_id=2,module='seo',action_type='monthly_report',
                        title='合成月报',params={'kind':'report','month':'2026-09','history':[]},status='in_progress',
                        created_by='7',assignee_role='seo_advisor'))
            project,_=await configure(client,operation)
            project=await action(client,project,'start')
            await automation.dispatch_project(KEY,sessions=sessions)
            async with sessions() as db:
                run=await core.read_run(db,KEY,project['current_run_id'])
                step=run['steps'][0]
                assert step['status']=='succeeded'
                assert not step['calls'] and step['fee_state']=='not_called'
                events=(await core.events_page(db,KEY,run['id']))['items']
                assert next(e for e in events if e['code']=='step_succeeded')['actor_kind']=='system'
                row=await db.get(SeoTask,int(step['evidence_refs'][0].split(':')[1]))
                assert row.completion_evidence is None and row.status!='done'
                if operation=='monthly_report':
                    assert row.params['report']['sha256'] and row.params['phase']=='awaiting_advisor_explanation'
                else: assert row.params['onsite']['phase']=='draft'
    asyncio.run(scenario())


@pytest.mark.parametrize('stop',['pause','end_project'])
def test_legacy_tenant_rank_batch_preserves_other_site_and_skips_owned_site(stop,monkeypatch):
    from app import seo_serp,seo_automation_boundary as boundary
    from app.api import seo as seo_api
    from app.models.seo import SeoKeywordAsset,SeoBrandAsset,SeoRankSnapshot,SeoMetricSnapshot,SeoSerpResult
    async def scenario():
        async with environment() as (sessions,task,client):
            async with sessions.begin() as db:
                for model in (SeoBrandAsset,SeoRankSnapshot,SeoMetricSnapshot,SeoSerpResult):
                    await db.execute(CreateTable(model.__table__,include_foreign_key_constraints=[]))
                db.add(SeoSite(id=8,tenant_id=4,tenant_module_id=1,name='other synthetic site',domain='other.example.com',
                    canonical_domain='other.example.com',status='active',site_settings={}))
                db.add(SeoKeywordAsset(id=80,tenant_id=4,site_id=8,keyword='other keyword',status='active'))
            project,_=await configure(client,'ranking_collect')
            project=await action(client,project,'start')
            await action(client,project,stop)
            settings=seo_serp.get_settings().model_copy(update={'chinaz_api_enabled':True,
                'chinaz_baidu_pc_ranking_api_key':'synthetic-not-real','chinaz_api_base_url':'https://synthetic.invalid'})
            monkeypatch.setattr(seo_serp,'get_settings',lambda:settings)
            monkeypatch.setattr(boundary,'async_session_factory',sessions)
            calls=[]
            async def provider(*args,**kwargs):
                calls.append(kwargs['params']['domain'])
                return httpx.Response(200,json={'StateCode':1,'Result':{'Ranks':[
                    {'RankStr':'1-2','Url':'https://other.example.com/p','Title':'其他网站'}]}},
                    request=httpx.Request('GET','https://synthetic.invalid'))
            monkeypatch.setattr(seo_serp,'metered_request',provider)
            async with sessions() as db:
                result=await seo_api.collect_rank_serp_for_tenant(session=db,tenant_id=4,use_ai=False)
                assert result['snapshots']==1 and result['provider_requests']==1
                assert result['errors']==[{'keyword_id':20,'code':'automation_legacy_owned'}]
            assert calls==['other.example.com']
            async with sessions() as db:
                assert list(await db.scalars(select(SeoRankSnapshot.site_id)))==[8]
    asyncio.run(scenario())
