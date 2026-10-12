"""Native SEO + external candidate broker, isolated loopback PostgreSQL only.

Opt in with SEO_DISTRIBUTION_INTEGRATION=true. No real platform transport.
Shared files are loaded into native app namespaces, never copied over app code.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import subprocess
import sys
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.schema import CreateTable

from app.database import get_session
from app.api.seo import _content_confirmation_hash
from app.security.auth import issue_token
from app.models.user import User
from app.models.role import Role
from app.models.tenant import Tenant
from app.models.module_workspace import SeoSite, TenantModule
from app.models.seo import (SeoContentAsset, SeoContentConfirmation, SeoDistributionVariant,
    SeoDistributionConnection, SeoSiteAdvisorAssignment, SeoKeywordAsset)

pytestmark = pytest.mark.skipif(os.getenv('SEO_DISTRIBUTION_INTEGRATION') != 'true',
    reason='explicit local broker integration opt-in required')
CENTRAL = Path('D:/SNIPERS国内版/ai_sni-worktrees/distribution-control-20261011')
BASE = '/api/distribution/v1'
SCOPE = {'module':'seo','tenant_id':4,'scope_id':2}
QUERY = {**SCOPE,'platform':'wechat-article'}
EVIDENCE = []


@pytest.fixture(autouse=True)
def no_platform_http(monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail('Real HTTP transport is forbidden in local broker integration')
    monkeypatch.setattr(httpx.AsyncHTTPTransport,'handle_async_request',forbidden)


@pytest.fixture(scope='module')
def shared():
    import app
    import app.api
    previous = {}
    fingerprints = {}
    pinned=os.getenv('SEO_DISTRIBUTION_ROOT_COMMIT')
    if pinned: assert re.fullmatch(r'[a-f0-9]{40}',pinned),'Pin the full reviewed local root commit'
    central_commit = pinned or subprocess.check_output(['git','-C',str(CENTRAL),'rev-parse','HEAD'],text=True).strip()
    def central_bytes(path):
        if pinned:return subprocess.check_output(['git','-C',str(CENTRAL),'show',pinned+':'+path])
        return (CENTRAL/path).read_bytes()
    try:
        publication_enabled=b'distribution_publication_results' in central_bytes('app/api/distribution.py')
        modules=[('app.distribution_contract','app/distribution_contract.py'),
            ('app.distribution_control','app/distribution_control.py'),
            ('app.distribution_scheduling','app/distribution_scheduling.py')]
        if publication_enabled:
            modules.extend([('app.distribution_publication_verify','app/distribution_publication_verify.py'),
                ('app.distribution_publication_results','app/distribution_publication_results.py')])
        modules.append(('app.api.distribution','app/api/distribution.py'))
        for name, path in modules:
            parent, leaf = name.rsplit('.',1)
            package = sys.modules[parent]
            previous[name] = (sys.modules.get(name), package, getattr(package,leaf,None))
            raw = central_bytes(path)
            fingerprints[path] = hashlib.sha256(raw).hexdigest()
            spec = importlib.util.spec_from_file_location(name,CENTRAL/path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            setattr(package,leaf,module)
            exec(compile(raw,str(CENTRAL/path),'exec'),module.__dict__)
        ddl = central_bytes('scripts/distribution_control_schema.sql')
        fingerprints['scripts/distribution_control_schema.sql'] = hashlib.sha256(ddl).hexdigest()
        scheduling_ddl = central_bytes('scripts/distribution_scheduling_schema.sql')
        fingerprints['scripts/distribution_scheduling_schema.sql'] = hashlib.sha256(scheduling_ddl).hexdigest()
        combined=ddl.decode('utf-8-sig')+'\n'+scheduling_ddl.decode('utf-8-sig')
        if publication_enabled:
            publication_ddl=central_bytes('scripts/distribution_publication_schema.sql')
            fingerprints['scripts/distribution_publication_schema.sql']=hashlib.sha256(publication_ddl).hexdigest()
            combined+='\n'+publication_ddl.decode('utf-8-sig')
        yield sys.modules['app.api.distribution'], combined
    finally:
        report = {'native_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            'native_dirty':bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip()),
            'central_path':str(CENTRAL),'central_commit':central_commit,'central_source':'git_commit' if pinned else 'working_tree',
            'central_file_sha256':fingerprints,'cases':EVIDENCE,
            'transport':'in-process ASGI; actual JWT/native DB/adapter; zero platform calls',
            'database':'loopback 127.0.0.1:55443/distribution_control_test; random schemas cleaned'}
        (Path(os.environ['TEMP'])/'seo-distribution-broker-evidence.json').write_text(
            json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        for name,(old,package,attribute) in reversed(list(previous.items())):
            leaf = name.rsplit('.',1)[1]
            if old is None: sys.modules.pop(name,None)
            else: sys.modules[name] = old
            if attribute is None: delattr(package,leaf)
            else: setattr(package,leaf,attribute)


@asynccontextmanager
async def environment(shared):
    router, ddl = shared
    schema = 'seo_broker_test_' + uuid4().hex
    engine = create_async_engine('postgresql+asyncpg://distribution_test@127.0.0.1:55443/distribution_control_test',
        connect_args={'server_settings':{'search_path':schema,'lock_timeout':'5000','statement_timeout':'15000'}})
    sessions = async_sessionmaker(engine,expire_on_commit=False)
    created = False
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
            for model in (Tenant,Role,User,TenantModule,SeoSite,SeoSiteAdvisorAssignment,SeoKeywordAsset,
                SeoContentAsset,SeoContentConfirmation,SeoDistributionConnection,SeoDistributionVariant):
                await conn.execute(CreateTable(model.__table__,include_foreign_key_constraints=[]))
            raw = await conn.get_raw_connection()
            await raw.driver_connection.execute(ddl)
        async with sessions.begin() as db:
            content = SeoContentAsset(id=40,tenant_id=4,site_id=2,content_type='article',title='selection article',
                draft='<p>selection article body</p>',status='ready',version_count=3,keyword_ids=[20],
                reviewed_by=7,reviewed_at=datetime(2026,10,10))
            db.add_all([Tenant(id=4,name='synthetic'),Role(id=5,name='advisor',permissions={
                'seo.content':'edit','seo.site':'edit'}),Role(id=6,name='operator',permissions={
                'settings.accounts':'edit','settings.customers':'edit'}),
                User(id=7,username='synthetic-advisor',password_hash='unused',role_id=5,is_active=True),
                User(id=8,username='synthetic-admin',password_hash='unused',role_id=6,is_active=True),
                TenantModule(id=1,tenant_id=4,module_code='seo',status='active'),
                SeoSite(id=2,tenant_id=4,tenant_module_id=1,name='synthetic',domain='example.com',
                    canonical_domain='example.com',status='active'),
                SeoSiteAdvisorAssignment(id=3,tenant_id=4,site_id=2,advisor_user_id=7,active=True),
                SeoKeywordAsset(id=20,tenant_id=4,site_id=2,keyword='selection',status='active'),content,
                SeoDistributionConnection(id=50,tenant_id=4,platform_code='wechat_official',name='synthetic',
                    mode='manual',enabled=True,status='manual_required'),
                SeoDistributionVariant(id=60,tenant_id=4,content_asset_id=40,connection_id=50,
                    platform_code='wechat_official',source_version=3,revision_number=2,status='approved',
                    title='selection article',content='<p>selection article body</p>',reviewed_by=7,
                    reviewed_at=datetime(2026,10,10)),
                SeoContentConfirmation(id=70,tenant_id=4,site_id=2,content_asset_id=40,content_version=3,
                    content_hash=_content_confirmation_hash(content),decision='approve',actor_mode='advisor_proxy',
                    actor_user_id=7,actor_role_name='advisor',created_at=datetime(2026,10,10))])
        app = FastAPI()
        async def database():
            async with sessions() as db: yield db
        app.dependency_overrides[get_session] = database
        app.include_router(router.router)
        from app.api.seo_distribution_media import router as media_router
        app.include_router(media_router)
        async with sessions() as db:
            headers = {'Authorization':'Bearer '+issue_token(await db.get(User,7))}
            admin = {'Authorization':'Bearer '+issue_token(await db.get(User,8))}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://synthetic') as client:
            yield client,sessions,headers,admin
    finally:
        try:
            if created:
                assert schema.startswith('seo_broker_test_') and len(schema)==48
                async with engine.begin() as conn: await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        finally: await engine.dispose()


async def request(client, method, path, headers=None, expected=200, **kwargs):
    response = await client.request(method,BASE+path,headers=headers,**kwargs)
    assert response.status_code==expected, (path,response.status_code,response.text)
    assert response.headers.get('cache-control')=='no-store'
    return response.json()


async def setup_task(client,headers,admin,action='preflight',platform='wechat-article'):
    query={**QUERY,'platform':platform}
    items = (await request(client,'GET','/sources',headers,params=query))['items']
    assert len(items)==1 and set(items[0])=={'variant_id','source_revision','title','platform'}
    preview = await request(client,'GET','/source',headers,params={**query,'variant_id':60})
    assert preview['source_revision']==items[0]['source_revision']
    device = (await request(client,'POST','/devices',admin,json={'label':'synthetic'}))['device']
    binding = (await request(client,'POST','/bindings',admin,json={**query,'device_id':device['id'],
        'account_id':'synthetic-account','external_account_id':'synthetic-external',
        'confirm_account_ownership':True}))['binding']
    project = (await request(client,'POST','/control',headers,json={**SCOPE,'action':'start',
        'expected_revision':0,'request_id':str(uuid4())}))['project']
    assert project['state']=='running'
    payload = {**SCOPE,'variant_id':60,'binding_id':binding['id'],'source_revision':preview['source_revision'],
        'expected_digest':preview['content_digest'],'action':action,'confirm_reviewed_content':True,
        'request_id':str(uuid4())}
    if action=='publish': payload['confirm_manual_publication']=True
    task = (await request(client,'POST','/tasks',headers,json=payload))['task']
    assert task['status']=='queued'
    return device,task,payload


async def exchange(client,device,receipts=None):
    return await request(client,'POST','/device/exchange',{'Authorization':'Bearer '+device['credential']},
        json={'contractVersion':1,'deviceId':device['id'],'receipts':receipts or []})


def receipt(task, status='succeeded'):
    from app.distribution_control import now_ms
    return {**{key:task[key] for key in ('customerId','projectId','deviceId','accountId','platform','contentDigest','leaseId')},
        'receiptId':str(uuid4()),'sequence':1,'contractVersion':1,'taskId':task['id'],
        'contentVersion':task['content']['version'],'status':status,
        'code':'PREFLIGHT_OK' if status=='succeeded' else 'HUMAN_REQUIRED','at':now_ms(),
        'evidence':'none','publicUrl':None}


@pytest.mark.parametrize('action',['preflight','handoff'])
def test_native_jwt_broker_roundtrip(shared,action):
    async def scenario():
        async with environment(shared) as (client,sessions,headers,admin):
            device,task,_ = await setup_task(client,headers,admin,action)
            envelope = await exchange(client,device)
            assert len(envelope['tasks'])==len(envelope['grants'])==1
            dispatched = envelope['tasks'][0]
            assert dispatched['id']==task['id'] and dispatched['projectId']=='seo-2'
            assert dispatched['content']['body']=='<p>selection article body</p>'
            status = 'succeeded' if action=='preflight' else 'awaiting-human'
            result = await exchange(client,device,[receipt(dispatched,status)])
            assert result['receiptAcks'][0]['status']==status
            tasks = (await request(client,'GET','/tasks',headers,params=SCOPE))['items']
            assert tasks[0]['status']==status
            EVIDENCE.append({'case':'roundtrip','action':action,'status':status,'projectId':dispatched['projectId']})
    asyncio.run(scenario())


@pytest.mark.parametrize('change',['review','replacement','assignment'])
def test_native_xiaohongshu_upload_freeze_device_download_and_revoke(shared,change,monkeypatch):
    from test_seo_distribution_media_postgres import picture
    async def scenario():
        async with environment(shared) as (client,sessions,headers,admin):
            async with sessions.begin() as db:
                connection=await db.connection()
                raw=await connection.get_raw_connection()
                await raw.driver_connection.execute((Path(__file__).parents[1]/'scripts/seo_distribution_media_schema.sql').read_text())
                variant=await db.get(SeoDistributionVariant,60)
                variant.platform_code='xiaohongshu'; variant.created_by=7
                (await db.get(SeoDistributionConnection,50)).platform_code='xiaohongshu'
                db.add(User(id=9,username='native-reviewer',password_hash='unused',role_id=5,is_active=True))
                db.add(SeoSiteAdvisorAssignment(id=4,tenant_id=4,site_id=2,advisor_user_id=9,active=True))
            async with sessions() as db:
                reviewer={'Authorization':'Bearer '+issue_token(await db.get(User,9))}
            prefix='/api/seo/distribution-media/variants/60'
            params={'tenant_id':4,'site_id':2}
            async def upload_native():
                preview=(await client.get(prefix,headers=headers,params=params)).json()
                response=await client.post(prefix+'/assets',headers=headers,data={**params,
                    'expected_token':preview['edit_token']},files=[('files',('image.png',picture(),'image/png')),
                    ('files',('image.jpg',picture('JPEG','blue'),'image/jpeg'))])
                assert response.status_code==200,response.text
                return response.json()
            draft=await upload_native()
            approved=await client.post(prefix+'/review',headers=reviewer,json={**params,
                'expected_token':draft['edit_token'],'set_id':draft['set_id']})
            assert approved.status_code==200,approved.text
            snapshot=approved.json()
            device,task,_=await setup_task(client,headers,admin,'handoff','xiaohongshu-image')
            envelope=await exchange(client,device)
            assert envelope['tasks'][0]['content']==snapshot['content']
            for item in snapshot['content']['assets']:
                path=BASE+'/device/tasks/'+task['id']+'/assets/'+item['id']
                response=await client.get(path,headers={'Authorization':'Bearer '+device['credential']})
                assert response.status_code==200,response.text
                assert len(response.content)==item['bytes'] and hashlib.sha256(response.content).hexdigest()==item['sha256']
                assert response.headers['content-type']==item['mediaType']
                assert response.headers['etag']=='"'+item['sha256']+'"'
                assert (await client.get(path,headers={'Authorization':'Bearer '+'invalid'*10})).status_code==401
            from PIL import ImageFile
            with monkeypatch.context() as unsafe:
                unsafe.setattr(ImageFile,'LOAD_TRUNCATED_IMAGES',True)
                denied=await client.get(path,headers={'Authorization':'Bearer '+device['credential']})
                assert denied.status_code==503,denied.text
                assert ImageFile.LOAD_TRUNCATED_IMAGES is True
            if change=='replacement': await upload_native()
            else:
                async with sessions.begin() as db:
                    if change=='review': (await db.get(SeoDistributionVariant,60)).status='draft'
                    else: (await db.get(SeoSiteAdvisorAssignment,3)).active=False
            rejected=await client.get(path,headers={'Authorization':'Bearer '+device['credential']})
            assert rejected.status_code in {403,409},rejected.text
            fenced=await exchange(client,device)
            assert fenced['tasks']==[] and fenced['grants']==[]
            EVIDENCE.append({'case':'native-xiaohongshu-bytes','assets':len(snapshot['content']['assets']),
                'change':change,'revoked_download_status':rejected.status_code,'old_grants_removed':True,
                'permissive_decoder_download_status':503})
    asyncio.run(scenario())


@pytest.mark.parametrize('change',['body','review','assignment','new_draft'])
@pytest.mark.parametrize('leased',[False,True])
def test_changed_native_authorization_fences_old_dispatch(shared,change,leased):
    async def scenario():
        async with environment(shared) as (client,sessions,headers,admin):
            device,task,payload = await setup_task(client,headers,admin)
            if leased: assert len((await exchange(client,device))['tasks'])==1
            async with sessions.begin() as db:
                if change=='body': (await db.get(SeoDistributionVariant,60)).content='<p>selection changed body</p>'
                elif change=='review': (await db.get(SeoDistributionVariant,60)).status='pending_review'
                elif change=='assignment': (await db.get(SeoSiteAdvisorAssignment,3)).active=False
                else: db.add(SeoDistributionVariant(id=61,tenant_id=4,content_asset_id=40,connection_id=50,
                    platform_code='wechat_official',source_version=3,revision_number=3,status='draft',title='new',content='new'))
            envelope = await exchange(client,device)
            assert envelope['tasks']==[] and envelope['grants']==[]
            async with sessions() as db:
                row = (await db.execute(text('SELECT status,revoked FROM distribution_tasks WHERE id=:id'),
                    {'id':UUID(task['id'])})).mappings().one()
                assert row['revoked'] and row['status']==('unknown' if leased else 'canceled')
            await request(client,'POST','/tasks',headers,expected=403 if change=='assignment' else 409,
                json={**payload,'request_id':str(uuid4())})
            EVIDENCE.append({'case':'fenced','change':change,'leased':leased,'status':row['status']})
    asyncio.run(scenario())


def test_real_auth_scope_and_admin_routes(shared):
    async def scenario():
        async with environment(shared) as (client,sessions,headers,admin):
            await request(client,'GET','/sources',expected=401,params=QUERY)
            await request(client,'GET','/sources',headers,expected=403,params={**QUERY,'tenant_id':9})
            await request(client,'GET','/sources',headers,expected=403,params={**QUERY,'scope_id':9})
            await request(client,'POST','/devices',headers,expected=403,json={'label':'not-admin'})
            assert len((await request(client,'GET','/sources',headers,params=QUERY))['items'])==1
            async with sessions.begin() as db: (await db.get(Role,5)).permissions={'seo.site':'edit','seo.content':'view'}
            await request(client,'GET','/sources',headers,expected=403,params=QUERY)
            await request(client,'GET','/source',headers,expected=403,params={**QUERY,'variant_id':60})
            EVIDENCE.append({'case':'jwt-current-role-scope-admin','result':'passed'})
    asyncio.run(scenario())


@pytest.mark.parametrize('change',['review','body','assignment'])
def test_changed_source_cannot_accept_success_receipt(shared,change):
    async def scenario():
        async with environment(shared) as (client,sessions,headers,admin):
            device,task,_ = await setup_task(client,headers,admin)
            dispatched = (await exchange(client,device))['tasks'][0]
            async with sessions.begin() as db:
                if change=='review': (await db.get(SeoDistributionVariant,60)).status='pending_review'
                elif change=='body': (await db.get(SeoDistributionVariant,60)).content='<p>selection changed</p>'
                else: (await db.get(SeoSiteAdvisorAssignment,3)).active=False
            result = await exchange(client,device,[receipt(dispatched)])
            async with sessions() as db:
                row = (await db.execute(text('SELECT status,revoked FROM distribution_tasks WHERE id=:id'),
                    {'id':UUID(task['id'])})).mappings().one()
            EVIDENCE.append({'case':'receipt-after-authorization-changed','change':change,'observed_status':row['status']})
            assert row['status']=='unknown' and row['revoked']
            assert result['tasks']==[] and result['grants']==[]
    asyncio.run(scenario())


@pytest.mark.parametrize('body',['selection '+'a'*100000,'selection '+'😀'*50000],ids=['characters','utf16'])
def test_central_list_filters_long_native_sources_without_truncation(shared,body):
    """Native-valid long articles stay intact but are not executor candidates."""
    from app.seo_distribution_sources import list_sources, load_source
    async def scenario():
        async with environment(shared) as (client,sessions,headers,admin):
            async with sessions.begin() as db:
                db.add(SeoDistributionConnection(id=51,tenant_id=4,platform_code='wechat_official',name='synthetic-long',
                    mode='manual',enabled=True,status='manual_required'))
                db.add(SeoDistributionVariant(id=61,tenant_id=4,content_asset_id=40,connection_id=51,
                    platform_code='wechat_official',source_version=3,revision_number=2,status='approved',
                    title='selection long article',content=body,reviewed_by=7,reviewed_at=datetime(2026,10,10)))
            async with sessions() as db:
                native = await list_sources(db,7,4,2,'wechat-article')
                assert {item['variant_id'] for item in native}=={60,61}
                normal = await load_source(db,7,4,2,60,'wechat-article')
            items = (await request(client,'GET','/sources',headers,params=QUERY))['items']
            assert len(items)==1 and items[0]['variant_id']==60
            preview = await request(client,'GET','/source',headers,params={**QUERY,'variant_id':60})
            assert preview['content']==normal['content']
            assert preview['source_revision']==items[0]['source_revision']==normal['source_revision']
            assert preview['content']['body']=='<p>selection article body</p>'
            rejected = await request(client,'GET','/source',headers,expected=409,params={**QUERY,'variant_id':61})
            assert rejected['detail']['code']=='source_changed'
            async with sessions() as db:
                assert (await db.get(SeoDistributionVariant,61)).content==body
            EVIDENCE.append({'case':'content-length-filter-regression','native_characters':len(body),
                'utf16_units':len(body.encode('utf-16-le'))//2,'native_listed':True,'central_listed':False,
                'preview_status':409,'preview_code':'source_changed','normal_article_fully_readable':True,
                'stored_long_body_unchanged':True,'resolution':'central list validates complete source against ApprovedContent'})
    asyncio.run(scenario())
