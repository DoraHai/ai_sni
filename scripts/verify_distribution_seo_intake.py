"""Opt-in real native SEO + central PG/JWT integration in a separate process.

Reads the exact clean native tree, never copies/edits it. All SQL is in the
native fixture's temporary schema on an explicitly guarded loopback database.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--seo-root',type=Path,required=True)
    parser.add_argument('--seo-head',required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--dependency-path',type=Path)
    parser.add_argument('--controls-enabled',action='store_true')
    args=parser.parse_args()
    if args.dependency_path: sys.path.append(str(args.dependency_path.resolve()))
    root=args.seo_root.resolve(); central=Path(__file__).resolve().parents[1]
    head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    if head!=args.seo_head or subprocess.check_output(['git','-C',str(root),'status','--porcelain'],text=True).strip():
        raise RuntimeError('Exact clean native SEO commit required')
    from sqlalchemy.engine import make_url
    url=make_url(os.environ['SEO_WORKFLOW_TEST_DATABASE_URL'])
    if url.host!='127.0.0.1' or url.port!=55443 or url.database!='seo_workflow_test' or url.username!='distribution_test' or url.query:
        raise RuntimeError('Explicit isolated SEO database on 127.0.0.1:55443 required')
    os.environ['DATABASE_URL']=str(url)
    os.environ.update(BAIDU_APP_ID='synthetic',BAIDU_SECRET_KEY='synthetic',BAIDU_DEFAULT_USERNAME='synthetic',
        BAIDU_DEFAULT_UCID='1',BAIDU_SELF_ACCESS_TOKEN='synthetic',BAIDU_SELF_TOKEN_EXPIRES_AT='2099-01-01T00:00:00Z',
        CRYPTO_MASTER_KEY_B64='AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=',
        ADMIN_API_KEY='synthetic_queue_admin',JWT_SECRET='synthetic_distribution_queue_integration_secret')
    if args.controls_enabled: os.environ.update(API_CONTROLS_ENABLED='true',API_METERING_ENABLED='true',DASHSCOPE_API_KEY='',DEEPSEEK_API_KEY='')
    sys.path.insert(0,str(root));sys.path.insert(0,str(root/'tests'))
    from test_seo_distribution_sources_postgres import fixture
    import app,app.api
    app.__path__.append(str(central/'app'));app.api.__path__.append(str(central/'app/api'))
    from app.api.distribution import router
    from app import distribution_queue as queue,distribution_control as core,distribution_planning as planner
    from app.models.seo import SeoDistributionVariant,SeoSiteAdvisorAssignment
    from app.models.role import Role
    from app.models.user import User
    from app.database import get_session
    from app.security.auth import issue_token
    from fastapi import FastAPI
    import httpx
    from sqlalchemy import text
    scope={'module':'seo','tenant_id':4,'scope_id':2}

    async def run():
        async with fixture() as sessions:
            async with sessions.begin() as db:
                connection=await db.connection();raw=await connection.get_raw_connection()
                for name in ('control','scheduling','publication','queue','planning'):
                    await raw.driver_connection.execute((central/f'scripts/distribution_{name}_schema.sql').read_text(encoding='utf-8'))
                db.add(Role(id=8,name='synthetic-admin',permissions={'settings.accounts':'edit','settings.customers':'edit'}))
                db.add(User(id=8,username='synthetic-admin',password_hash='unused',role_id=8,is_active=True))
                (await db.get(SeoDistributionVariant,60)).status='pending_review'
            async def session_dep():
                async with sessions() as db: yield db
            api=FastAPI();api.include_router(router);api.dependency_overrides[get_session]=session_dep
            async with sessions() as db:
                tokens={i:issue_token(await db.get(User,i)) for i in (7,8)}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api),base_url='https://synthetic.invalid') as client:
                async def call(method,path,actor=7,**kwargs):
                    r=await client.request(method,'/api/distribution/v1'+path,headers={'Authorization':'Bearer '+tokens[actor]},**kwargs)
                    assert r.status_code==200,(path,r.status_code,r.text)
                    return r.json()
                device=(await call('POST','/devices',8,json={'label':'native queue synthetic'}))['device']
                binding=(await call('POST','/bindings',8,json={**scope,'device_id':device['id'],'account_id':'synthetic-local',
                    'external_account_id':'synthetic-platform','platform':'wechat-article','confirm_account_ownership':True}))['binding']
                await call('POST','/project-channel',json={**scope,'binding_id':binding['id'],'content_type':'article','enabled':True,'expected_revision':0,'request_id':str(uuid4())})
                await call('POST','/control',json={**scope,'action':'start','expected_revision':0,'request_id':str(uuid4())})
                assert not (await call('GET','/queue',params=scope))['items']
                await queue.run_once(sessions)
                pending=(await call('GET','/queue',params=scope))['items'][0]
                assert pending['state']=='awaiting-review' and pending['source_revision'] is None
                async with sessions.begin() as db: (await db.get(SeoDistributionVariant,60)).status='approved'
                await queue.run_once(sessions)
                approved=(await call('GET','/queue',params=scope))['items'][0]
                assert approved['id']==pending['id'] and approved['draft_version']==pending['draft_version']
                assert approved['state']=='awaiting-authorization' and approved['source_revision']
                await call('POST','/channel-permission',8,json={'platform':'wechat-article','content_type':'article','enabled':True,'expected_revision':0,'request_id':str(uuid4())})
                await call('POST','/account-policy',8,json={'binding_id':binding['id'],'expected_revision':0,'enabled':True,'timezone':'Asia/Shanghai',
                    'daily_limit':5,'min_interval_seconds':0,'windows':[{'start':0,'end':1440}],'request_id':str(uuid4())})
                await queue.run_once(sessions)
                assert (await call('GET','/queue',params=scope))['items'][0]['state']=='awaiting-adaptation'
                await call('POST','/control',json={**scope,'action':'pause','expected_revision':1,'request_id':str(uuid4())})
                await queue.run_once(sessions);assert (await call('GET','/queue',params=scope))['items'][0]['state']=='paused'
                await call('POST','/control',json={**scope,'action':'resume','expected_revision':2,'request_id':str(uuid4())})
                await queue.run_once(sessions)
                assert (await call('GET','/queue',params=scope))['items'][0]['state']=='awaiting-adaptation'
                model_calls=[]
                async def controlled_model(snap,request_id):
                    model_calls.append(str(request_id))
                    assert snap['tenant_id']==4 and snap['actor_id']==7
                    return {'items':[{'queue_id':i['queue_id'],'at':i['earliest_at']} for i in snap['items']]}
                provider=None
                if args.controls_enabled:
                    from distribution_planning_integration_support import install,Provider
                    await install(sessions,root,'seo')
                    provider=Provider();provider.activate()
                    from app.distribution_planning_gateway import suggest
                    async def controlled_model(snap,request_id):
                        model_calls.append(str(request_id));return await suggest(snap,request_id)
                try:
                    await planner.run_once(sessions,controlled_model)
                    await planner.run_once(sessions,controlled_model)
                finally:
                    if provider:provider.restore()
                if provider:
                    assert len(provider.calls)==1
                    async with sessions() as db:
                        event=await core.one(db,'SELECT * FROM api_usage_events')
                        assert event['tenant_id']==4 and event['user_id']==7 and event['module']=='seo' and event['job_ref']==model_calls[0]

                plan_view=await call('GET','/plans',params=scope)
                assert len(model_calls)==1 and len(plan_view['items'])==1 and plan_view['items'][0]['basis']=='ai'
                async with sessions.begin() as db:
                    old=await db.get(SeoDistributionVariant,60)
                    db.add(SeoDistributionVariant(id=61,tenant_id=4,content_asset_id=40,connection_id=50,platform_code='wechat_official',
                        source_version=3,revision_number=3,status='pending_review',title=old.title,content=old.content))
                await queue.run_once(sessions)
                records=(await call('GET','/queue',params=scope))['items']
                assert len(records)==2 and next(q for q in records if q['variant_id']==60)['state']=='superseded'
                assert next(q for q in records if q['variant_id']==61)['state']=='awaiting-review'
                async with sessions.begin() as db: (await db.get(SeoSiteAdvisorAssignment,3)).active=False
                await queue.run_once(sessions)
                await planner.run_once(sessions,controlled_model)
                async with sessions() as db:
                    assert (await core.one(db,'SELECT state FROM distribution_plans'))['state']=='blocked'
                assert len(model_calls)==1
                denied=await client.get('/api/distribution/v1/queue',params=scope,headers={'Authorization':'Bearer '+tokens[7]})
                assert denied.status_code==403
                async with sessions() as db:
                    assert (await core.one(db,'SELECT count(*) AS n FROM distribution_tasks'))['n']==0
                    assert (await core.one(db,'SELECT * FROM distribution_queue_scans'))['reason']=='AUTHORIZATION_REVOKED'
        return {'schema':1,'native_head':head,'native_sha256':hashlib.sha256((root/'app/seo_distribution_sources.py').read_bytes()).hexdigest(),
            'central_head':subprocess.check_output(['git','-C',str(central),'rev-parse','HEAD'],text=True).strip(),
            'central_files':{str(p.relative_to(central)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (central/'app/distribution_queue.py',central/'app/api/distribution.py',central/'app/distribution_contract.py')},
            'verified':['real-native-pending-intake','approval-reuses-queue-id','live-source-gates','global-authorization',
                'policy-checked-unverified-path-blocked','pause-resume','new-variant-invalidates-old','JWT-revocation','no-execution-grants','GET-read-only','native-planner-authorization','native-planner-idempotency','native-planner-revocation'],
            'real_platform_publication':False,'production_ready':False,'api_controls_enabled':args.controls_enabled}
    report=asyncio.run(run());args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__': main()
