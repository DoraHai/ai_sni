"""Reproducible controls-enabled gateway proof using exact assembled native code."""
import argparse,asyncio,json,os,sys
from pathlib import Path
from uuid import uuid4
from distribution_assembled_worker import assemble

def main():
 p=argparse.ArgumentParser();p.add_argument('--native-root',type=Path,required=True);p.add_argument('--module',choices=['seo','geo'],required=True);p.add_argument('--report',type=Path,required=True);p.add_argument('--dependency-path',type=Path);a=p.parse_args()
 if a.dependency_path:sys.path.append(str(a.dependency_path.resolve()))
 raw=os.environ['DISTRIBUTION_TEST_DATABASE_URL']
 from sqlalchemy.engine import make_url
 url=make_url(raw)
 assert (url.host,url.port,url.database,url.username)==('127.0.0.1',55443,'distribution_control_test','distribution_test') and not url.query
 os.environ.update(DATABASE_URL=raw,BAIDU_APP_ID='synthetic',BAIDU_SECRET_KEY='synthetic',BAIDU_DEFAULT_USERNAME='synthetic',BAIDU_DEFAULT_UCID='1',BAIDU_SELF_ACCESS_TOKEN='synthetic',BAIDU_SELF_TOKEN_EXPIRES_AT='2099-01-01T00:00:00Z',CRYPTO_MASTER_KEY_B64='AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=',JWT_SECRET='synthetic-planning-integration-secret',ADMIN_API_KEY='synthetic-planning-admin',DASHSCOPE_API_KEY='',DEEPSEEK_API_KEY='',API_CONTROLS_ENABLED='true',API_METERING_ENABLED='true',BAIDU_WRITE_DRY_RUN='true')
 from sqlalchemy.ext.asyncio import create_async_engine
 from sqlalchemy import text
 import subprocess
 from uuid import uuid4
 central=Path(__file__).resolve().parents[1]
 async def run():
  suffix=uuid4().hex;schema='assembled_entry_'+suffix;role='assembled_'+suffix
  engine=create_async_engine(raw,connect_args={'server_settings':{'search_path':schema}})
  manifest=a.report.with_suffix('.manifest.json')
  try:
   async with engine.begin() as db:
    await db.execute(text('CREATE SCHEMA '+schema));await db.execute(text('CREATE TABLE tenants(id bigint PRIMARY KEY)'))
    c=await db.get_raw_connection()
    for source in (a.native_root/'scripts/api_metering_schema.sql',a.native_root/'scripts/api_controls_schema.sql',*[central/('scripts/distribution_'+n+'_schema.sql') for n in ('control','scheduling','publication','queue','planning','execution','capability_registration')]):
     await c.driver_connection.execute(source.read_text(encoding='utf-8-sig').replace('BEGIN;','').replace('COMMIT;',''))
    await db.execute(text('CREATE ROLE '+role+' LOGIN'))
    await db.execute(text('ALTER ROLE '+role+' SET search_path TO '+schema))
    await db.execute(text('GRANT USAGE ON SCHEMA '+schema+' TO '+role))
    await db.execute(text('GRANT SELECT ON ALL TABLES IN SCHEMA '+schema+' TO '+role))
   env=dict(os.environ);env['DATABASE_URL']=str(url.set(username=role))
   result=await asyncio.to_thread(subprocess.run,[sys.executable,str(central/'scripts/distribution_assembled_worker.py'),'--native-root',str(a.native_root.resolve()),'--module',a.module,'--once','--manifest',str(manifest)],env=env,cwd=central,capture_output=True,text=True)
   assert result.returncode==0,result.stderr
   async with engine.connect() as db:
    for table in ('distribution_tasks','distribution_plan_requests','api_usage_events'):assert await db.scalar(text('SELECT count(*) FROM '+table))==0
   a.report.write_text(json.dumps({'module':a.module,'exact_cli_entry_executed':True,'no_work_no_tasks_no_ai_events':True,'manifest':json.loads(manifest.read_text(encoding='utf-8'))},indent=2)+'\n',encoding='utf-8')
  finally:
   async with engine.begin() as db:
    await db.execute(text('DROP SCHEMA IF EXISTS '+schema+' CASCADE'))
    await db.execute(text('DROP ROLE IF EXISTS '+role))
   await engine.dispose()
 asyncio.run(run());print(json.dumps({'module':a.module,'exact_cli_entry_executed':True}))
if __name__=='__main__':main()
