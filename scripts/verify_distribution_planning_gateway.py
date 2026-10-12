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
    args=parser.parse_args()
    if args.dependency_path: sys.path.append(str(args.dependency_path.resolve()))
    root=args.seo_root.resolve(); central=Path(__file__).resolve().parents[1]
    head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    if head!=args.seo_head or subprocess.check_output(['git','-C',str(root),'status','--porcelain'],text=True).strip():
        raise RuntimeError('Exact clean native SEO commit required')
    from sqlalchemy.engine import make_url
    url=make_url(os.environ['DISTRIBUTION_TEST_DATABASE_URL'])
    if url.host!='127.0.0.1' or url.port!=55443 or url.database!='distribution_control_test' or url.username!='distribution_test' or url.query:
        raise RuntimeError('Explicit isolated SEO database on 127.0.0.1:55443 required')
    os.environ['DATABASE_URL']=str(url)
    os.environ.update(BAIDU_APP_ID='synthetic',BAIDU_SECRET_KEY='synthetic',BAIDU_DEFAULT_USERNAME='synthetic',
        BAIDU_DEFAULT_UCID='1',BAIDU_SELF_ACCESS_TOKEN='synthetic',BAIDU_SELF_TOKEN_EXPIRES_AT='2099-01-01T00:00:00Z',
        CRYPTO_MASTER_KEY_B64='AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=',
        ADMIN_API_KEY='synthetic_queue_admin',JWT_SECRET='synthetic_distribution_queue_integration_secret')
    sys.path.insert(0,str(root));sys.path.insert(0,str(root/'tests'))
    import app
    app.__path__.append(str(central/'app'))
    from app import api_metering as meter
    from app.distribution_planning_gateway import suggest,GatewayFailure
    from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
    from sqlalchemy import text
    import httpx
    os.environ.update(API_METERING_ENABLED='true',API_CONTROLS_ENABLED='false',DASHSCOPE_API_KEY='synthetic-planning-key')
    from app.config import get_settings
    get_settings().dashscope_api_key='synthetic-planning-key'
    schema='planning_meter_'+uuid4().hex
    engine=create_async_engine(str(url),connect_args={'server_settings':{'search_path':schema}})
    sessions=async_sessionmaker(engine,expire_on_commit=False)
    meter.async_session_factory=sessions
    calls=[];mode=['valid']
    original=httpx.AsyncClient
    def transport(request):
        payload=json.loads(request.content);calls.append(payload)
        assert 'tools' not in payload and payload['max_tokens']==1500
        if mode[0]=='timeout': raise httpx.ReadTimeout('synthetic timeout',request=request)
        content='broken' if mode[0]=='invalid' else '{"items":[]}'
        return httpx.Response(200,json={'id':'synthetic-provider','choices':[{'message':{'content':content}}],'usage':{'prompt_tokens':100,'completion_tokens':12}})
    httpx.AsyncClient=lambda **kwargs: original(transport=httpx.MockTransport(transport),**kwargs)
    snap={'tenant_id':4,'module':'seo','actor_id':7,'scope_id':2,'items':[]}
    async def run():
        async with engine.begin() as db:
            await db.execute(text('CREATE SCHEMA '+schema))
            raw=await db.get_raw_connection()
            ddl=(root/'scripts/api_metering_schema.sql').read_text(encoding='utf-8').replace('BEGIN;','').replace('COMMIT;','')
            await raw.driver_connection.execute(ddl)
        try:
            job=uuid4();assert await suggest(snap,job)=={'items':[]}
            mode[0]='invalid'
            try: await suggest(snap,uuid4())
            except GatewayFailure as exc: assert exc.code=='AI_INVALID_OUTPUT'
            else: raise AssertionError('invalid reply accepted')
            mode[0]='timeout'
            try: await suggest(snap,uuid4())
            except httpx.ReadTimeout as exc: assert exc.provider_attempted
            else: raise AssertionError('timeout accepted')
            async with sessions() as db:
                rows=(await db.execute(text('SELECT * FROM api_usage_events ORDER BY started_at'))).mappings().all()
                assert len(rows)==3 and all(r['tenant_id']==4 and r['user_id']==7 and r['module']=='seo' and r['operation']=='distribution_planning' for r in rows)
                assert rows[0]['job_ref']==str(job) and rows[0]['prompt_tokens']==100 and rows[0]['completion_tokens']==12
                assert [r['state'] for r in rows]==['succeeded','succeeded','unknown']
                assert all(r['credential_ref']!='synthetic-planning-key' for r in rows)
            os.environ['API_METERING_ENABLED']='false'
            try: await suggest(snap,uuid4())
            except GatewayFailure as exc: assert exc.code=='AI_METERING_REQUIRED'
            else: raise AssertionError('unmetered call accepted')
            assert len(calls)==3
            args.report.write_text(json.dumps({'native_head':head,'provider':'synthetic transport only','actual_main_metering':True,'events':3,'attribution':'tenant 4/user 7/seo/distribution_planning/job_ref','invalid_output_still_metered':True,'timeout_persisted_unknown':True,'disabled_meter_no_http':True,'api_controls_enabled':False},indent=2),encoding='utf-8')
        finally:
            async with engine.begin() as db: await db.execute(text('DROP SCHEMA '+schema+' CASCADE'))
            await engine.dispose()
    asyncio.run(run())

if __name__=='__main__': main()
