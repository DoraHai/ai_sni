"""Actual GEO/JWT/advisor planning on controls-enabled assembled main gateway."""
import argparse,asyncio,json,os,sys
from pathlib import Path
from uuid import uuid4
from distribution_assembled_worker import assemble

def main():
 p=argparse.ArgumentParser();p.add_argument('--native-root',type=Path,required=True);p.add_argument('--report',type=Path,required=True);p.add_argument('--dependency-path',type=Path);a=p.parse_args()
 if a.dependency_path:sys.path.append(str(a.dependency_path.resolve()))
 raw=os.environ['GEO_TEST_POSTGRES_URL']
 from sqlalchemy.engine import make_url
 u=make_url(raw);assert (u.host,u.port,u.database,u.username)==('127.0.0.1',55507,'geo_ci','geo_ci') and not u.query
 os.environ.update(DATABASE_URL=raw,BAIDU_APP_ID='synthetic',BAIDU_SECRET_KEY='synthetic',BAIDU_DEFAULT_USERNAME='synthetic',BAIDU_DEFAULT_UCID='1',BAIDU_SELF_ACCESS_TOKEN='synthetic',BAIDU_SELF_TOKEN_EXPIRES_AT='2099-01-01T00:00:00Z',CRYPTO_MASTER_KEY_B64='AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=',JWT_SECRET='synthetic-planning-integration-secret',ADMIN_API_KEY='synthetic-planning-admin',DASHSCOPE_API_KEY='',DEEPSEEK_API_KEY='',API_CONTROLS_ENABLED='true',API_METERING_ENABLED='true',BAIDU_WRITE_DRY_RUN='true')
 report=assemble(a.native_root,'geo')
 from test_geo_distribution_publication_broker_postgres import fixture,call,SCOPE
 from test_geo_distribution_intake_broker_postgres import configured
 from app.geo.content.review import apply_decision,apply_submit,invalidate_review
 from app.models import GeoContentTask,GeoChannelVariant
 from sqlalchemy import text
 from distribution_planning_integration_support import install,Provider
 async def run():
  async with fixture() as (sessions,client,modules,advisor,admin,other):
   from app import distribution_planning as planner
   async with sessions.begin() as db:
    c=await db.connection();rawc=await c.get_raw_connection();await rawc.driver_connection.execute((Path(__file__).parent/'distribution_planning_schema.sql').read_text(encoding='utf-8'))
    invalidate_review(await db.get(GeoContentTask,50))
   binding=await configured(client,advisor,admin)
   r=await call(client,admin,'POST','/account-policy',json={'binding_id':binding,'enabled':True,'expected_revision':0,'timezone':'UTC','daily_limit':5,'min_interval_seconds':600,'windows':[{'start':0,'end':1440}],'request_id':str(uuid4())});assert r.status_code==200,r.text
   await install(sessions,a.native_root,'geo');provider=Provider();provider.activate()
   queue=modules['distribution_queue'];checks=[]
   try:
    await queue.run_once(sessions);await planner.run_once(sessions);assert len(provider.calls)==0
    async with sessions.begin() as db:
     task=await db.get(GeoContentTask,50);apply_submit(task,submitter_id=7);apply_decision(task,decision='approved',note=None,reviewer_id=12)
    await queue.run_once(sessions);await planner.run_once(sessions)
    r=await call(client,advisor,'GET','/plans',params=SCOPE);assert r.status_code==200,r.text
    assert len(provider.calls)==1 and r.json()['items'][0]['basis']=='ai';checks+=['pending-no-ai','native-review-allows-metered-ai']
    assert (await call(client,other,'GET','/plans',params=SCOPE)).status_code==403;checks.append('foreign-advisor-denied')
    r=await call(client,advisor,'POST','/control',json={**SCOPE,'action':'pause','expected_revision':1,'request_id':str(uuid4())});assert r.status_code==200
    await planner.run_once(sessions);assert len(provider.calls)==1
    r=await call(client,advisor,'GET','/plans',params=SCOPE);assert r.json()['items'][0]['state']=='blocked';checks.append('pause-invalidates-no-ai')
    r=await call(client,advisor,'POST','/control',json={**SCOPE,'action':'resume','expected_revision':2,'request_id':str(uuid4())});assert r.status_code==200
    await queue.run_once(sessions);await planner.run_once(sessions);assert len(provider.calls)==2;checks.append('resume-fresh-admission')
    async with sessions.begin() as db:
     invalidate_review(await db.get(GeoContentTask,50));(await db.get(GeoChannelVariant,91)).body_markdown+='\n新的修订。'
    await queue.run_once(sessions);await planner.run_once(sessions);assert len(provider.calls)==2
    r=await call(client,advisor,'GET','/plans',params=SCOPE);assert all(p['state']!='planned' for p in r.json()['items']);checks.append('edit-invalidates-old-plan')
    async with sessions.begin() as db:
     task=await db.get(GeoContentTask,50);apply_submit(task,submitter_id=7);apply_decision(task,decision='approved',note=None,reviewer_id=12)
    await queue.run_once(sessions)
    async def pause_in_call():
     response=await call(client,advisor,'POST','/control',json={**SCOPE,'action':'pause','expected_revision':3,'request_id':str(uuid4())});assert response.status_code==200
    provider.on_call=pause_in_call
    await planner.run_once(sessions);assert len(provider.calls)==3
    async with sessions() as db:assert (await db.execute(text('SELECT state FROM distribution_plan_requests ORDER BY updated_at DESC LIMIT 1'))).scalar()=='stale'
    checks.append('pause-during-provider-call-discards-response')
    provider.on_call=None
    response=await call(client,advisor,'POST','/control',json={**SCOPE,'action':'resume','expected_revision':4,'request_id':str(uuid4())});assert response.status_code==200
    await queue.run_once(sessions)
    async def revoke_in_call():
     async with sessions.begin() as db:await db.execute(text('UPDATE users SET is_active=false WHERE id=7'))
    provider.on_call=revoke_in_call
    await planner.run_once(sessions);assert len(provider.calls)==4
    async with sessions() as db:assert (await db.execute(text('SELECT state FROM distribution_plan_requests ORDER BY updated_at DESC LIMIT 1'))).scalar()=='stale'
    checks.append('revocation-during-provider-call-discards-response')
    async with sessions() as db:
     events=(await db.execute(text('SELECT * FROM api_usage_events'))).mappings().all();assert len(events)==4 and all(e['tenant_id']==1 and e['user_id']==7 and e['module']=='geo' and e['job_ref'] for e in events)
     for table in ('distribution_tasks','distribution_publish_reservations','geo_publications'):assert await db.scalar(text('SELECT count(*) FROM '+table))==0
    checks+=['real-metering-attribution','no-grants-or-publications'];return checks
   finally:provider.restore()
 report['checks']=asyncio.run(run());report.update(api_controls_enabled=True,real_http=False);a.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report['checks']))
if __name__=='__main__':main()
