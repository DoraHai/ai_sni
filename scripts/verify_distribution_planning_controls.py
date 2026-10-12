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
 report=assemble(a.native_root,a.module)
 from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
 from sqlalchemy import text
 from distribution_planning_integration_support import control_checks
 async def run():
  schema='planning_controls_'+uuid4().hex;engine=create_async_engine(raw,connect_args={'server_settings':{'search_path':schema}});sessions=async_sessionmaker(engine,expire_on_commit=False)
  try:
   async with engine.begin() as db:
    await db.execute(text('CREATE SCHEMA '+schema))
    await db.execute(text('CREATE TABLE tenants(id bigint PRIMARY KEY)'))
    await db.execute(text('INSERT INTO tenants VALUES(4)'))
   report['checks']=await control_checks(sessions,a.module,a.native_root)
   report.update(api_controls_enabled=True,real_http=False)
  finally:
   async with engine.begin() as db:await db.execute(text('DROP SCHEMA '+schema+' CASCADE'))
   await engine.dispose()
 asyncio.run(run());a.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps({'module':a.module,'checks':report['checks']}))
if __name__=='__main__':main()
