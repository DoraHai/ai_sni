"""Real bearer validation + isolated PostgreSQL; synthetic source adapters only."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import httpx
from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.engine import make_url

URL=os.environ.get('DISTRIBUTION_TEST_DATABASE_URL','')
if not URL:
    pytest.skip('dedicated distribution test database not configured',allow_module_level=True)
parsed=make_url(URL)
if (parsed.drivername!='postgresql+asyncpg' or parsed.host!='127.0.0.1' or parsed.port!=55443
    or parsed.database!='distribution_control_test' or parsed.username!='distribution_test' or parsed.query):
    raise RuntimeError('Dedicated loopback distribution test database required')
os.environ.update(DATABASE_URL=URL,BAIDU_APP_ID='synthetic',BAIDU_SECRET_KEY='synthetic',
    BAIDU_DEFAULT_USERNAME='synthetic',BAIDU_DEFAULT_UCID='1',BAIDU_SELF_ACCESS_TOKEN='synthetic',
    BAIDU_SELF_TOKEN_EXPIRES_AT='2099-01-01T00:00:00Z',
    CRYPTO_MASTER_KEY_B64='AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=',
    ADMIN_API_KEY='synthetic_distribution_admin_key',JWT_SECRET='synthetic_distribution_jwt_signing_key')

from app.database import get_session
from app.api.distribution import router
from app import distribution_control as core
from app.distribution_contract import content_digest
from app.security import auth

BASE='/api/distribution/v1'
SCOPE={'module':'seo','tenant_id':4,'scope_id':19}
CONTENT={'version':'seo_variant_11_r1','title':'合成审核稿 😀','body':'这是合成正文，不调用真实平台。','assets':[]}


class Sources:
    def __init__(self): self.content=deepcopy(CONTENT); self.revoked=False
    async def authorize_scope(self,db,actor,tenant,scope):
        user=await core.one(db,'SELECT u.is_active,u.tenant_id,r.permissions FROM users u JOIN roles r ON r.id=u.role_id WHERE u.id=:id',id=actor)
        if self.revoked or not user or not user['is_active'] or actor!=7 or (tenant,scope)!=(4,19) or user['permissions'].get('seo.content')!='edit':
            raise core.problem('scope_forbidden',403)
    async def load_source(self,db,actor,tenant,scope,variant,platform):
        await self.authorize_scope(db,actor,tenant,scope)
        if variant!=11 or platform!='wechat-article': raise core.problem('source_changed')
        return {**SCOPE,'variant_id':11,'source_revision':self.content['version'],'content':deepcopy(self.content)}
    async def list_sources(self,db,actor,tenant,scope,platform):
        await self.authorize_scope(db,actor,tenant,scope)
        return [{'variant_id':11,'source_revision':self.content['version'],'title':self.content['title'],'platform':platform}]


@asynccontextmanager
async def fixture(monkeypatch):
    schema='distribution_test_'+uuid4().hex
    engine=create_async_engine(URL,pool_size=8,max_overflow=0,connect_args={'server_settings':{
        'search_path':schema,'lock_timeout':'5000','statement_timeout':'15000'}})
    sessions=async_sessionmaker(engine,expire_on_commit=False)
    async with engine.begin() as db:
        await db.execute(text(f'CREATE SCHEMA "{schema}"'))
        raw=await db.get_raw_connection()
        await raw.driver_connection.execute('''
          CREATE TABLE tenants(id bigint PRIMARY KEY); INSERT INTO tenants VALUES(4),(5);
          CREATE TABLE seo_sites(id bigint PRIMARY KEY,tenant_id bigint); INSERT INTO seo_sites VALUES(19,4),(20,5);
          CREATE TABLE geo_projects(id bigint PRIMARY KEY,tenant_id bigint); INSERT INTO geo_projects VALUES(10,4);
          CREATE TABLE roles(id bigint PRIMARY KEY,name varchar(50),description text,permissions jsonb,is_system boolean,created_at timestamp);
          CREATE TABLE users(id bigint PRIMARY KEY,username varchar(50),display_name varchar(50),password_hash varchar(100),role_id bigint,
            tenant_id bigint,is_active boolean,last_login_at timestamp,failed_login_attempts integer,last_failed_login_at timestamp,
            locked_until timestamp,created_at timestamp);
          INSERT INTO roles VALUES
            (1,'合成顾问',NULL,'{"seo.site":"edit","seo.content":"edit"}',false,now()),
            (2,'合成超管',NULL,'{"settings.accounts":"edit","settings.customers":"edit"}',false,now()),
            (3,'合成客户',NULL,'{"seo.site":"view","seo.content":"view"}',false,now());
          INSERT INTO users(id,username,role_id,tenant_id,is_active,failed_login_attempts,created_at)
            VALUES(7,'advisor',1,NULL,true,0,now()),(8,'admin',2,NULL,true,0,now()),(9,'customer',3,4,true,0,now());
        ''')
        await raw.driver_connection.execute((Path(__file__).parents[1]/'scripts/distribution_control_schema.sql').read_text(encoding='utf-8'))
        await raw.driver_connection.execute((Path(__file__).parents[1]/'scripts/distribution_scheduling_schema.sql').read_text(encoding='utf-8'))
        await raw.driver_connection.execute((Path(__file__).parents[1]/'scripts/distribution_publication_schema.sql').read_text(encoding='utf-8'))
        await raw.driver_connection.execute((Path(__file__).parents[1]/'scripts/distribution_queue_schema.sql').read_text(encoding='utf-8'))
        await raw.driver_connection.execute((Path(__file__).parents[1]/'scripts/distribution_planning_schema.sql').read_text(encoding='utf-8'))
        await raw.driver_connection.execute((Path(__file__).parents[1]/'scripts/distribution_execution_schema.sql').read_text(encoding='utf-8-sig'))
        await raw.driver_connection.execute((Path(__file__).parents[1]/'scripts/distribution_capability_registration_schema.sql').read_text(encoding='utf-8-sig'))
    async def session():
        async with sessions() as db: yield db
    sources=Sources(); monkeypatch.setattr(core,'adapter',lambda module:sources)
    app=FastAPI(); app.include_router(router); app.dependency_overrides[get_session]=session
    tokens={uid:auth.issue_token(SimpleNamespace(id=uid)) for uid in (7,8,9)}
    client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://synthetic.invalid')
    async def call(method,path,actor=7,**kwargs):
        result=await client.request(method,BASE+path,headers={'Authorization':'Bearer '+tokens[actor]},**kwargs)
        assert result.headers.get('cache-control')=='no-store'
        return result
    value=SimpleNamespace(app=app,client=client,call=call,sessions=sessions,sources=sources,tokens=tokens)
    try: yield value
    finally:
        await client.aclose()
        assert schema.startswith('distribution_test_') and len(schema)==50
        async with engine.begin() as db: await db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


async def prepare(f,action='preflight',external='synthetic-public-account',device=None):
    if not device:
        response=await f.call('POST','/devices',actor=8,json={'label':'合成设备'})
        assert response.status_code==200,response.text; device=response.json()['device']
    response=await f.call('POST','/bindings',actor=8,json={**SCOPE,'device_id':device['id'],
        'account_id':'synthetic-local-'+device['id'],'external_account_id':external,'platform':'wechat-article','confirm_account_ownership':True})
    assert response.status_code==200,response.text; binding=response.json()['binding']
    if action=='publish':
        schedules=(await f.call('GET','/account-policies',actor=8)).json()['items']
        schedule=next(s for s in schedules if s['binding_id']==binding['id'])
        if schedule['policy'] is None:
            result=await f.call('POST','/account-policy',actor=8,json={'binding_id':binding['id'],'expected_revision':0,
                'enabled':True,'timezone':'Asia/Shanghai','min_interval_seconds':0,'daily_limit':100,
                'windows':[{'start':0,'end':1440}],'request_id':str(uuid4())})
            assert result.status_code==200,result.text
    current=(await f.call('GET','/scope',params=SCOPE)).json()['project']
    if current['revision']==0:
        response=await f.call('POST','/control',json={**SCOPE,'action':'start','expected_revision':0,'request_id':str(uuid4())})
        assert response.status_code==200,response.text
    request={**SCOPE,'variant_id':11,'binding_id':binding['id'],'source_revision':f.sources.content['version'],
        'expected_digest':content_digest(f.sources.content),'action':action,'confirm_reviewed_content':True,
        'confirm_manual_publication':action=='publish','request_id':str(uuid4())}
    return device,request


async def device_exchange(f,device,receipts=None):
    return await f.client.post(BASE+'/device/exchange',headers={'Authorization':'Bearer '+device['credential']},
        json={'contractVersion':1,'deviceId':device['id'],'receipts':receipts or []})


def test_admin_bindings_revoke_and_immutable_identity(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            device,request=await prepare(f,'handoff')
            binding_id=request['binding_id']
            value=(await f.call('GET','/bindings',actor=8)).json()
            assert value['items'][0]['external_account_id']=='synthetic-public-account'
            assert (await f.call('GET','/bindings')).status_code==403
            assert (await f.call('POST',f'/bindings/{binding_id}/revoke')).status_code==403
            assert (await f.call('POST','/tasks',json=request)).status_code==200
            assert len((await device_exchange(f,device)).json()['tasks'])==1
            assert (await f.call('POST',f'/bindings/{binding_id}/revoke',actor=8,json={})).status_code==200
            assert not (await device_exchange(f,device)).json()['tasks']
            assert (await f.call('GET','/tasks',params=SCOPE)).json()['items'][0]['status']=='unknown'
            assert (await f.call('POST','/tasks',json={**request,'request_id':str(uuid4())})).status_code==409
            binding={**SCOPE,'device_id':device['id'],'account_id':'synthetic-local-'+device['id'],
                'external_account_id':'different-public-account','platform':'wechat-article','confirm_account_ownership':True}
            assert (await f.call('POST','/bindings',actor=8,json=binding)).json()['detail']['code']=='binding_identity_immutable'
            binding['external_account_id']='synthetic-public-account'
            assert (await f.call('POST','/bindings',actor=8,json=binding)).status_code==200
            assert not (await device_exchange(f,device)).json()['tasks']
            binding['tenant_id']=5
            assert (await f.call('POST','/bindings',actor=8,json=binding)).status_code==404
    
    asyncio.run(run())


def receipt(task,status,code,*,evidence='none',url=None,at=None):
    return {'receiptId':str(uuid4()),'sequence':{'queued':1,'running':2,'awaiting-human':3}.get(status,4),
        'contractVersion':1,'taskId':task['id'],**{k:task[k] for k in ('customerId','projectId','deviceId','accountId','platform')},
        'contentVersion':task['content']['version'],'contentDigest':task['contentDigest'],'leaseId':task['leaseId'],
        'status':status,'code':code,'at':at or core.now_ms(),'evidence':evidence,'publicUrl':url}


def test_authenticated_lifecycle_and_receipt_reconciliation(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            device,req=await prepare(f); created=await f.call('POST','/tasks',json=req)
            assert created.status_code==200,created.text
            assert (await f.call('POST','/tasks',json=req)).json()==created.json()
            task=(await device_exchange(f,device)).json()['tasks'][0]
            assert task['projectId']=='seo-19' and task['content']==CONTENT
            done=receipt(task,'succeeded','PREFLIGHT_OK')
            for _ in range(2):
                result=await device_exchange(f,device,[done]); assert result.status_code==200,result.text
                assert result.json()['receiptAcks']==[{k:done[k] for k in ('receiptId','taskId','leaseId','sequence','status','at')}]
            older=receipt(task,'running','DISPATCHED',at=done['at']-1)
            assert (await device_exchange(f,device,[older])).status_code==200
            assert (await f.call('GET','/tasks',params=SCOPE)).json()['items'][0]['status']=='succeeded'
            assert len((await f.call('GET','/events',params=SCOPE)).json()['items'])>=4
            assert 'credential' not in (await f.call('GET','/devices',actor=8)).text
    asyncio.run(run())


def test_list_filters_complete_content_exceeding_utf16_contract(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            query={**SCOPE,'platform':'wechat-article'}
            assert len((await f.call('GET','/sources',params=query)).json()['items'])==1
            f.sources.content['body']='😀'*50001
            assert not (await f.call('GET','/sources',params=query)).json()['items']
            assert (await f.call('GET','/source',params={**query,'variant_id':11})).status_code==409
            f.sources.revoked=True
            assert (await f.call('GET','/sources',params=query)).status_code==403
    asyncio.run(run())


def test_response_budget_keeps_unoffered_tasks_queued(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            f.sources.content['body']='文'*99999
            device,request=await prepare(f,'handoff')
            assert (await f.call('POST','/tasks',json=request)).status_code==200
            for i in range(5):
                value=(await f.call('POST','/bindings',actor=8,json={**SCOPE,'device_id':device['id'],
                    'account_id':f'synthetic-extra-{i}','external_account_id':f'synthetic-official-{i}',
                    'platform':'wechat-article','confirm_account_ownership':True})).json()['binding']
                assert (await f.call('POST','/tasks',json={**request,'binding_id':value['id'],'request_id':str(uuid4())})).status_code==200
            response=await device_exchange(f,device); assert response.status_code==200
            envelope=response.json(); assert 0<len(envelope['tasks'])<6
            assert len(core.canonical(envelope).encode())<=900000
            states=(await f.call('GET','/tasks',params=SCOPE)).json()['items']
            assert sum(item['status']=='leased' for item in states)==len(envelope['tasks'])
            assert any(item['status']=='queued' for item in states)
            acknowledged=[receipt(t,'awaiting-human','HUMAN_REQUIRED') for t in envelope['tasks']]
            next_envelope=(await device_exchange(f,device,acknowledged)).json()
            first_ids={t['id'] for t in envelope['tasks']}
            assert next_envelope['tasks'] and all(t['id'] not in first_ids for t in next_envelope['tasks'])
            assert all(any(g['id']==t['grantId'] for g in next_envelope['grants']) for t in envelope['tasks'])
    asyncio.run(run())


@pytest.mark.parametrize('change',['edit','revoke','expire'])
def test_receipt_adoption_rechecks_current_authorization(monkeypatch,change):
    async def run():
        async with fixture(monkeypatch) as f:
            device,req=await prepare(f,'publish')
            assert (await f.call('POST','/tasks',json=req)).status_code==200
            task=(await device_exchange(f,device)).json()['tasks'][0]
            if change=='edit': f.sources.content['body']='合成修改稿'
            elif change=='revoke': f.sources.revoked=True
            else:
                async with f.sessions() as db:
                    await db.execute(text('UPDATE distribution_tasks SET grant_expires_at=:at'),{'at':core.now_ms()-1});await db.commit()
            done=receipt(task,'succeeded','HUMAN_PUBLISHED',evidence='human-reported',url='https://mp.weixin.qq.com/s/synthetic')
            response=await device_exchange(f,device,[done]); assert response.status_code==200
            async with f.sessions() as db:
                state=await core.one(db,'SELECT status,revoked,receipt FROM distribution_tasks')
                assert state['status']=='unknown' and state['revoked']
                assert state['receipt']['publicUrl']==done['publicUrl']
    asyncio.run(run())


@pytest.mark.parametrize('field,value',[('customerId','5'),('projectId','geo-19'),('accountId','other-account'),
    ('deviceId','other-device'),('leaseId','other-lease'),('contentDigest','f'*64),('contentVersion','other-revision')])
def test_cross_scope_receipts_are_rejected(monkeypatch,field,value):
    async def run():
        async with fixture(monkeypatch) as f:
            device,req=await prepare(f); assert (await f.call('POST','/tasks',json=req)).status_code==200
            task=(await device_exchange(f,device)).json()['tasks'][0]; invalid=receipt(task,'running','DISPATCHED'); invalid[field]=value
            response=await device_exchange(f,device,[invalid]); assert response.status_code==403
            assert not (await device_exchange(f,device)).json()['receiptAcks']
    asyncio.run(run())


def test_pause_resume_end_and_expired_late_receipt(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            device,req=await prepare(f,action='publish'); assert (await f.call('POST','/tasks',json=req)).status_code==200
            task=(await device_exchange(f,device)).json()['tasks'][0]
            for action,revision in [('pause',1),('resume',2),('end',3)]:
                result=await f.call('POST','/control',json={**SCOPE,'action':action,'expected_revision':revision,'request_id':str(uuid4())})
                assert result.status_code==200,result.text
                envelope=(await device_exchange(f,device)).json()
                if action=='pause': assert task['id'] in envelope['pausedTaskIds']
                if action=='resume': assert not envelope['pausedTaskIds'] and envelope['tasks'][0]['id']==task['id']
                if action=='end': assert not envelope['tasks']
            done=receipt(task,'succeeded','HUMAN_PUBLISHED',evidence='human-reported',url='https://mp.weixin.qq.com/s/synthetic-public?tracking=drop')
            assert (await device_exchange(f,device,[done])).status_code==200
            row=(await f.call('GET','/tasks',params=SCOPE)).json()['items'][0]
            assert row['status']=='unknown' and row['receipt']['publicUrl']=='https://mp.weixin.qq.com/s/synthetic-public'
            assert (await f.call('POST','/control',json={**SCOPE,'action':'resume','expected_revision':4,'request_id':str(uuid4())})).status_code==409
    asyncio.run(run())


def test_revocation_and_source_change_fence_queued_work(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            device,req=await prepare(f); assert (await f.call('POST','/tasks',json=req)).status_code==200
            f.sources.content['body']='合成改稿'
            assert not (await device_exchange(f,device)).json()['tasks']
            assert (await f.call('GET','/tasks',params=SCOPE)).json()['items'][0]['status']=='canceled'
            f.sources.revoked=True
            assert (await f.call('GET','/scope',params=SCOPE)).status_code==403
            assert (await f.call('GET','/tasks',params=SCOPE)).status_code==403
            assert (await f.call('GET','/events',params=SCOPE)).status_code==403
    asyncio.run(run())


def test_readonly_and_admin_key_cannot_authorize_work(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            device,req=await prepare(f)
            for path in ['/scope','/tasks','/events']:
                assert (await f.call('GET',path,actor=9,params=SCOPE)).status_code==403
            assert (await f.call('POST','/tasks',actor=9,json=req)).status_code==403
            assert (await f.call('POST','/devices',actor=7,json={'label':'forbidden'})).status_code==403
            result=await f.client.post(BASE+'/devices',headers={'X-API-Key':'synthetic_distribution_admin_key'},json={'label':'forbidden'})
            assert result.status_code==403
            async with f.sessions.begin() as db: await db.execute(text('UPDATE users SET is_active=false WHERE id=7'))
            assert (await f.call('POST','/tasks',json=req)).status_code==401
    asyncio.run(run())


def test_cross_device_duplicate_intent_and_unknown_no_retry(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            first,req1=await prepare(f,action='publish'); second,req2=await prepare(f,action='publish')
            outcomes=await asyncio.gather(f.call('POST','/tasks',json=req1),f.call('POST','/tasks',json=req2))
            assert sorted(r.status_code for r in outcomes)==[200,409]
            device=first if outcomes[0].status_code==200 else second
            task=(await device_exchange(f,device)).json()['tasks'][0]
            unknown=receipt(task,'unknown','EXECUTION_RESULT_UNKNOWN')
            assert (await device_exchange(f,device,[unknown])).status_code==200
            req={**req1,'request_id':str(uuid4())}
            result=await f.call('POST','/tasks',json=req)
            assert result.status_code==409 and result.json()['detail']['code']=='outcome_unknown'
    asyncio.run(run())


@pytest.mark.parametrize('status,code,evidence,url',[('succeeded','PREFLIGHT_OK','none',None),
    ('succeeded','HUMAN_PUBLISHED','simulation','https://mp.weixin.qq.com/s/valid'),
    ('succeeded','HUMAN_PUBLISHED','human-reported','https://evil.invalid/s/valid'),
    ('succeeded','HUMAN_PUBLISHED','human-reported',None)])
def test_publish_receipts_do_not_fake_platform_success(monkeypatch,status,code,evidence,url):
    async def run():
        async with fixture(monkeypatch) as f:
            device,req=await prepare(f,action='publish'); assert (await f.call('POST','/tasks',json=req)).status_code==200
            task=(await device_exchange(f,device)).json()['tasks'][0]
            result=await device_exchange(f,device,[receipt(task,status,code,evidence=evidence,url=url)])
            assert result.status_code==422
    asyncio.run(run())
