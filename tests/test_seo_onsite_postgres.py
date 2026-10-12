"""Concurrency uses only a dedicated loopback PostgreSQL database and owned schemas."""
import asyncio
from uuid import uuid4
import os
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.schema import CreateTable
from test_seo_workflow_postgres import database, ADVISOR
from app.api import seo_onsite as api
from app.models.seo import SeoSitePage
from app.models.seo_cockpit import SeoTask

pytestmark=pytest.mark.skipif(not os.getenv("SEO_WORKFLOW_TEST_DATABASE_URL"), reason="requires dedicated PostgreSQL")

def test_create_and_proposal_races_are_serialized_without_lost_history():
    async def run():
        async with database() as sessions:
            async with sessions() as db:
                await db.execute(CreateTable(SeoSitePage.__table__, include_foreign_key_constraints=[]))
                await db.commit()
            req=api.Create(tenant_id=4,site_id=2,request_id=uuid4(),work_type="startup",owner_name="维护人员")
            async def create():
                async with sessions() as db:
                    return await api.create(req,db,ADVISOR)
            rows=await asyncio.gather(*(create() for _ in range(5)))
            assert len({r["id"] for r in rows})==1
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(SeoTask))==1
            row=rows[0]
            async def save():
                async with sessions() as db:
                    try:
                        return await api.act(row["id"],api.Update(tenant_id=4,site_id=2,action="save_proposal",
                            expected_revision=1,items=row["workflow"]["items"]),db,ADVISOR)
                    except HTTPException as exc:
                        assert exc.status_code==409
                        return None
            results=await asyncio.gather(*(save() for _ in range(5)))
            assert sum(r is not None for r in results)==1
            async with sessions() as db:
                task=await db.get(SeoTask,row["id"])
                assert task.params["onsite"]["revision"]==2 and len(task.params["onsite"]["history"])==2
            async with sessions() as db:
                with pytest.raises(HTTPException) as err:
                    await api.create(req.model_copy(update={"owner_name":"其他人员"}),db,ADVISOR)
                assert err.value.status_code==409
    asyncio.run(run())


# Full HTTP/JWT advisor delivery below. Only DB dependency and outbound HTTP
# transports are replaced; auth, role/assignment lookup and checking are real.
from contextlib import asynccontextmanager
from pathlib import Path
import json
import subprocess
import httpx
from fastapi import FastAPI
from app.database import get_session
from app.api import auth as login_api, seo as seo_api, seo_onsite_ai as ai_api
from app import seo_onsite_ai_jobs as jobs, seo_crawler as crawler
from app.models.user import User
from app.models.role import Role
from app.models.module_workspace import SeoSite, TenantModule
from app.models.tenant import Tenant
from app.models.seo import SeoSiteAdvisorAssignment
from app.security.auth import hash_password
from test_seo_onsite_ai_postgres import fixture, supplier, real_metered_supplier, install_guard_tables, guard_response

HTTP_CLIENT = httpx.AsyncClient
TASKS='/api/v1/seo/workbench/onsite-tasks'
DELIVERY_SAMPLES=[]


async def capture_delivery(response):
    await response.aread()
    if 'application/json' not in response.headers.get('content-type',''): return
    body=response.json()
    if response.request.url.path.endswith('/login'):
        # Never persist the actual JWT or login request/password.
        body={'authenticated':response.status_code==200,'user_id':body.get('user',{}).get('id')}
    DELIVERY_SAMPLES.append({'case':os.environ.get('PYTEST_CURRENT_TEST','').split(' ')[0],
        'method':response.request.method,'path':response.request.url.raw_path.decode(),
        'status':response.status_code,'body':body})


@asynccontextmanager
async def delivery_environment(monkeypatch):
    async with fixture() as (sessions,seed):
        async with sessions.begin() as db:
            (await db.get(User,7)).password_hash=hash_password('synthetic-local-only-password')
            db.add_all([Role(id=6,name='synthetic-customer',permissions={
                'seo.site':'view','seo.content':'view','seo.keywords':'view'}),
                User(id=8,username='synthetic-customer',password_hash=hash_password('synthetic-local-only-password'),
                    role_id=6,tenant_id=4,is_active=True),
                SeoSite(id=8,tenant_id=4,tenant_module_id=1,name='other synthetic site',domain='other.example.com',
                    canonical_domain='other.example.com',status='active',site_settings={}),
                Tenant(id=9,name='other synthetic customer'),
                TenantModule(id=9,tenant_id=9,module_code='seo',status='active'),
                SeoSite(id=9,tenant_id=9,tenant_module_id=9,name='other customer site',domain='another.example.com',
                    canonical_domain='another.example.com',status='active',site_settings={})])
        await install_guard_tables(sessions)
        await sessions.kw['bind'].dispose()
        app=FastAPI()
        app.include_router(login_api.router)
        app.include_router(seo_api.router)
        async def db_dep():
            async with sessions() as db: yield db
        app.dependency_overrides[get_session]=db_dep
        state={'provider_calls':0,'page_calls':0,'page_matches':False,'during_provider':None,'during_page':None}
        async def provider(request):
            assert request.url.host=='api.deepseek.com'
            state['provider_calls']+=1
            if state['during_provider']: await state['during_provider']()
            return guard_response(request)
        async def page(request):
            assert request.url.host in {'example.com','www.example.com'}
            state['page_calls']+=1
            if state['during_page']: await state['during_page']()
            if request.url.path=='/robots.txt':
                return httpx.Response(200,text='User-agent: *\nAllow: /',headers={'content-type':'text/plain'},request=request)
            body=('<html><head><title>公开资料建议</title><meta name="description" content="公开资料建议">'
                '<meta name="keywords" content="selection"></head><body>selection '
                '<a href="https://example.com/guide">说明</a></body></html>') if state['page_matches'] else '<html><title>旧内容</title></html>'
            return httpx.Response(200,text=body,headers={'content-type':'text/html'},request=request)
        async def public(url): return '93.184.216.34'
        class MockPinnedTransport(crawler.PinnedAsyncHTTPTransport):
            async def handle_async_request(self,request):
                return await httpx.MockTransport(page).handle_async_request(request)
        monkeypatch.setattr(crawler,'_ensure_public_host',public)
        monkeypatch.setattr(crawler,'pinned_async_client',lambda **kwargs:HTTP_CLIENT(transport=MockPinnedTransport(),**kwargs))
        real_metered_supplier(monkeypatch,sessions,provider)
        async with HTTP_CLIENT(transport=httpx.ASGITransport(app=app),base_url='http://synthetic',
                event_hooks={'response':[capture_delivery]}) as client:
            async def login(username):
                response=await client.post('/api/v1/auth/login',json={
                    'username':username,'password':'synthetic-local-only-password'})
                assert response.status_code==200,response.text
                return {'Authorization':'Bearer '+response.json()['token']}
            advisor=await login('test')
            customer=await login('synthetic-customer')
            try: yield sessions,client,advisor,customer,state
            finally:
                root=Path(__file__).parents[1]
                data={'source':'real login + JWT + complete SEO ASGI router + isolated PG; MockTransport providers/pages; no browser',
                    'backend_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
                    'source_tree_clean':not bool(subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip()),
                    'scenarios':DELIVERY_SAMPLES}
                (Path(os.environ['TEMP'])/'seo-advisor-delivery-http-samples.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


async def http_task(client,headers):
    req={'tenant_id':4,'site_id':2,'request_id':str(uuid4()),'work_type':'monthly',
        'month':'2026-10','owner_name':'合成实施人员'}
    rows=await asyncio.gather(*(client.post(TASKS,headers=headers,json=req) for _ in range(2)))
    assert all(r.status_code==200 for r in rows),[r.text for r in rows]
    assert rows[0].json()['id']==rows[1].json()['id']
    return rows[0].json()


async def http_action(client,headers,row,action,**kwargs):
    return await client.post(TASKS+f"/{row['id']}/actions",headers=headers,json={
        'tenant_id':4,'site_id':2,'action':action,'expected_revision':row['workflow']['revision'],
        'note':'合成顾问的审核/实施依据',**kwargs})


async def http_ai(client,headers,row,sessions):
    req={'tenant_id':4,'site_id':2,'expected_revision':row['workflow']['revision'],
        'request_id':str(uuid4()),'mode':'initial'}
    requests=await asyncio.gather(*(client.post(TASKS+f"/{row['id']}/ai-proposal",json=req,
        headers={**headers,'X-Snipers-Onsite-Protocol':'durable-v1'}) for _ in range(2)))
    assert all(r.status_code==202 for r in requests),[r.text for r in requests]
    await jobs.execute_request(row['id'],4,2,req['request_id'],sessions=sessions)
    await jobs.execute_request(row['id'],4,2,req['request_id'],sessions=sessions)
    return await client.get(TASKS+f"/{row['id']}/ai-requests/{req['request_id']}?tenant_id=4&site_id=2",headers=headers)


async def prepared_http_task(client,headers,sessions):
    row=await http_task(client,headers)
    result=await http_ai(client,headers,row,sessions)
    assert result.status_code==200,result.text
    row=result.json()
    assert row['workflow']['phase']=='review' and row['request_run']['state']=='ready'
    assert row['completion_evidence'] is None
    assert (await http_action(client,headers,row,'approve')).status_code==422  # missing link needs advisor
    items=row['workflow']['items']
    for item in items:
        if item['kind']=='internal_link': item['expected']='https://example.com/guide'
    response=await http_action(client,headers,row,'save_proposal',items=items)
    assert response.status_code==200,response.text
    return response.json()


def test_real_login_jwt_advisor_ai_delivery_to_customer_readonly(monkeypatch,supplier):
    async def scenario():
        async with delivery_environment(monkeypatch) as (sessions,client,advisor,customer,state):
            assert (await client.get(TASKS+'?tenant_id=4&site_id=2')).status_code==401
            invalid=await client.post('/api/v1/auth/login',json={'username':'test','password':'wrong-synthetic'})
            assert invalid.status_code==401
            row=await prepared_http_task(client,advisor,sessions)
            # Current version and simultaneous approval: exactly one transition.
            stale=await http_action(client,advisor,row,'approve',expected_revision=1)
            assert stale.status_code==409
            responses=await asyncio.gather(*(http_action(client,advisor,row,'approve') for _ in range(3)))
            assert sorted(r.status_code for r in responses)==[200,409,409]
            row=next(r.json() for r in responses if r.status_code==200)
            assert row['workflow']['phase']=='implementation'
            row=(await http_action(client,advisor,row,'implement')).json()
            assert row['workflow']['phase']=='recheck'
            assert (await http_action(client,advisor,row,'accept')).status_code==409
            failed=await http_action(client,advisor,row,'recheck')
            assert failed.status_code==200,failed.text
            row=failed.json()
            assert not row['workflow']['recheck']['passed'] and row['completion_evidence'] is None
            assert (await http_action(client,advisor,row,'accept')).status_code==409
            state['page_matches']=True
            response=await http_action(client,advisor,row,'recheck')
            assert response.status_code==200,response.text
            row=response.json()
            assert row['workflow']['phase']=='acceptance' and row['workflow']['recheck']['passed']
            assert all(r['body_sha256'] and r['check_type']=='static_page_match' for r in row['workflow']['recheck']['results'])
            row=(await http_action(client,advisor,row,'accept')).json()
            assert row['workflow']['phase']=='done' and row['completion_evidence']['recheck']['passed']
            assert '不代表已收录' in row['completion_evidence']['note']
            read=await client.get(TASKS+'?tenant_id=4&site_id=2',headers=customer)
            assert read.status_code==200 and not read.json()['can_create']
            visible=next(r for r in read.json()['items'] if r['id']==row['id'])
            assert visible['allowed_actions']==[] and visible['workflow']['phase']=='done'
            assert state['provider_calls']==1 and state['page_calls']>=2
            async with sessions() as db:
                assert (await db.get(SeoTask,row['id'])).status=='done'
    asyncio.run(scenario())


@pytest.mark.parametrize('boundary',['customer','wrong_tenant','wrong_site','role_revoked','assignment_revoked'])
def test_real_http_delivery_authority_boundaries(boundary,monkeypatch,supplier):
    async def scenario():
        async with delivery_environment(monkeypatch) as (sessions,client,advisor,customer,state):
            row=await http_task(client,advisor)
            headers=customer if boundary=='customer' else advisor
            scope={'tenant_id':9} if boundary=='wrong_tenant' else {'site_id':8} if boundary=='wrong_site' else {}
            # Full-router module checks reject a mismatched active tenant/site
            # pair as non-operational before handler-level ownership checks.
            denied={403,404,409} if boundary=='wrong_tenant' else {403,404}
            if boundary in {'role_revoked','assignment_revoked'}:
                async with sessions.begin() as db:
                    if boundary=='role_revoked': (await db.get(Role,5)).permissions={'seo.site':'view','seo.content':'view'}
                    else: (await db.get(SeoSiteAdvisorAssignment,3)).active=False
            for action in ('save_proposal','approve','implement','recheck','accept'):
                response=await http_action(client,headers,row,action,**scope)
                assert response.status_code in denied,response.text
            response=await client.post(TASKS+f"/{row['id']}/ai-proposal",headers={**headers,'X-Snipers-Onsite-Protocol':'durable-v1'},
                json={'tenant_id':4,'site_id':2,'request_id':str(uuid4()),'mode':'initial','expected_revision':1,**scope})
            assert response.status_code in denied,response.text
            if boundary=='customer':
                response=await client.post(TASKS,headers=customer,json={'tenant_id':4,'site_id':2,'request_id':str(uuid4()),
                    'work_type':'monthly','month':'2026-10','owner_name':'客户'})
                assert response.status_code==403
                response=await client.post('/api/v1/seo/workbench/automation-projects/2/control',headers=customer,
                    json={'tenant_id':4,'request_id':str(uuid4()),'expected_version':0,'action':'start'})
                assert response.status_code==403
                response=await client.put('/api/v1/seo/workbench/automation-projects/2/control',headers=customer,
                    json={'tenant_id':4,'request_id':str(uuid4()),'expected_version':0,'configuration':{
                        'task_ids':[row['id']],'operations':['onsite_ai'],'cycle':{'mode':'once','enabled':False},
                        'limits':{'max_dispatches_per_run':1},'stop_condition':'drafts_ready_or_blocked','owner_user_id':8}})
                assert response.status_code==403
                assert (await client.get(TASKS+'?tenant_id=9&site_id=9',headers=customer)).status_code==403
            assert state['provider_calls']==state['page_calls']==0
    asyncio.run(scenario())


@pytest.mark.parametrize('stage',['ai','recheck'])
@pytest.mark.parametrize('revocation',['role','assignment','user','source'])
def test_real_http_delivery_rejects_late_result_after_role_revocation(stage,revocation,monkeypatch,supplier):
    async def scenario():
        async with delivery_environment(monkeypatch) as (sessions,client,advisor,customer,state):
            async def revoke():
                async with sessions.begin() as db:
                    if revocation=='role':
                        (await db.get(Role,5)).permissions={'seo.site':'view','seo.content':'view','seo.keywords':'view'}
                    elif revocation=='assignment': (await db.get(SeoSiteAdvisorAssignment,3)).active=False
                    elif revocation=='source': (await db.get(SeoSitePage,10)).url='https://example.com/moved'
                    else: (await db.get(User,7)).is_active=False
            if stage=='ai':
                row=await http_task(client,advisor)
                state['during_provider']=revoke
                await http_ai(client,advisor,row,sessions)
                async with sessions() as db:
                    w=(await db.get(SeoTask,row['id'])).params['onsite']
                    assert w['ai_run']['state']=='stale' and 'ai_proposal' not in w
            else:
                row=await prepared_http_task(client,advisor,sessions)
                row=(await http_action(client,advisor,row,'approve')).json()
                row=(await http_action(client,advisor,row,'implement')).json()
                state.update(page_matches=True,during_page=revoke)
                response=await http_action(client,advisor,row,'recheck')
                assert response.status_code==(409 if revocation=='source' else 403),response.text
                async with sessions() as db:
                    stored=await db.get(SeoTask,row['id'])
                    assert 'recheck' not in stored.params['onsite'] and stored.completion_evidence is None
                    assert 'onsite_recheck_quota' not in (await db.get(SeoSite,2)).site_settings
            assert state['provider_calls']==1
    asyncio.run(scenario())

