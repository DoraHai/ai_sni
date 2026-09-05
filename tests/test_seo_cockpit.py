import asyncio,os
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from uuid import uuid4
import pytest
from bs4 import BeautifulSoup
from fastapi import HTTPException
from sqlalchemy import MetaData,text,select
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from app.seo_cockpit_metrics import trend,metric_snapshot
from app.seo_image_evidence import image_alt_evidence
from app.seo_image_verification import evaluate_image_repair,enqueue_image_verification,verify_pending_images
from app.models.seo_cockpit import SeoTask,SeoImageVerification
from app.models.seo import SeoSitePage,SeoImageAltReview,SeoPageSnapshot,SeoCrawlRun,SeoKeywordAsset,SeoRankSnapshot,SeoContentAsset,SeoMetricSnapshot
from app.models.module_workspace import SeoSite
from app.models.seo import SeoBacklink
from app.security.auth import AuthContext
from app.api.seo_cockpit import TaskCreate,TaskUpdate,create_task,update_task,get_task,cancel_task

def test_trend_null_zero_and_direction_contract():
    assert trend(0,None) is None
    assert trend(None,1) is None
    assert trend(3,0)=={'direction':'up','change_pct':None,'change_abs':3}
    assert trend(0,0)=={'direction':'flat','change_pct':None,'change_abs':0}
    assert trend(3,6)=={'direction':'down','change_pct':-50,'change_abs':-3}

@pytest.mark.parametrize('html,decision,expected',[
 ('<img src="/a.png" alt="品牌产品">','informative','verified'),
 ('<img src="/a.png" alt="别的说明">','informative','unverified'),
 ('<img src="/a.png">','informative','unverified'),
 ('<p>图片消失</p>','informative','unverified'),
 ('<img src="/a.png" alt="品牌产品"><img src="/a.png" alt="品牌产品">','informative','unverified'),
 ('<img src="/a.png" alt="">','decorative','verified'),
 ('<a href="/x"><img src="/a.png" alt=""></a>','decorative','unverified'),
])
def test_image_completion_requires_unique_matching_observation(html,decision,expected):
    review=SimpleNamespace(source_url='https://brand.example/a.png',decision=decision,alt_suggestion='品牌产品',observed_alt_state='missing')
    old=SimpleNamespace(image_alt_evidence=image_alt_evidence(BeautifulSoup('<img src="/a.png">','html.parser'),'https://brand.example'))
    values={'image_alt_evidence':image_alt_evidence(BeautifulSoup(html,'html.parser'),'https://brand.example')}
    assert evaluate_image_repair(review,old,values)[0]==expected
    values['error_type']='timeout'
    assert evaluate_image_repair(review,old,values)[0]=='unavailable'

def run_database(scenario):
    url=os.environ.get('SEO_USAGE_TEST_DATABASE_URL')
    if not url:pytest.skip('requires PostgreSQL')
    async def run():
        schema='cockpit_'+uuid4().hex
        engine=create_async_engine(url,connect_args={'server_settings':{'search_path':schema}})
        try:
            async with engine.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                for model in [SeoSite,SeoSitePage,SeoImageAltReview,SeoPageSnapshot,SeoCrawlRun,SeoTask,SeoImageVerification,SeoKeywordAsset,SeoRankSnapshot,SeoContentAsset,SeoMetricSnapshot,SeoBacklink]:
                    table=model.__table__.to_metadata(MetaData())
                    for fk in list(table.foreign_key_constraints):table.constraints.remove(fk)
                    await connection.run_sync(lambda sync:table.create(sync))
            await scenario(async_sessionmaker(engine,expire_on_commit=False))
        finally:
            async with engine.begin() as connection:await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await engine.dispose()
    asyncio.run(run())

def test_database_task_metric_evidence_and_tenant_isolation():
    async def scenario(sessions):
        ctx=AuthContext(7,'test','operator',1,{'seo.site':'edit','seo.content':'edit','seo.keywords':'edit'})
        now=datetime.utcnow()
        async with sessions() as db:
            db.add(SeoSite(id=1,tenant_id=1,tenant_module_id=1,name='brand',domain='brand.example',canonical_domain='brand.example',status='active'))
            db.add(SeoContentAsset(id=1,tenant_id=1,site_id=1,title='Article',status='review'))
            db.add(SeoKeywordAsset(id=1,tenant_id=1,site_id=1,keyword='核心',priority='P0',status='active'))
            db.add(SeoKeywordAsset(id=2,tenant_id=2,site_id=1,keyword='其他客户',priority='P0',status='active'))
            db.add(SeoRankSnapshot(tenant_id=1,site_id=1,keyword_id=1,engine='baidu',device='desktop',region='全国',subject_type='own',rank=20,checked_at=now-timedelta(hours=2)))
            db.add(SeoRankSnapshot(tenant_id=1,site_id=1,keyword_id=1,engine='baidu',device='desktop',region='全国',subject_type='own',rank=5,checked_at=now-timedelta(hours=1)))
            db.add(SeoRankSnapshot(tenant_id=2,site_id=1,keyword_id=2,engine='baidu',device='desktop',region='全国',subject_type='own',rank=1,checked_at=now))
            await db.commit()
            first=await metric_snapshot(db,1,1)
            assert first[0]['value']==1 and all(x['trend_7d'] is None for x in first)
            db.add(SeoMetricSnapshot(tenant_id=1,site_id=1,metric_type='seo.ranking.top10_keyword_count',dimension='total',source='cockpit_observation',numeric_value=2,data_quality='verified',status='available',observed_at=now-timedelta(days=7,minutes=1)))
            await db.commit()
            assert (await metric_snapshot(db,1,1))[0]['trend_7d']=={'direction':'down','change_pct':-50,'change_abs':-1}
            task=await create_task(TaskCreate(tenant_id=1,site_id=1,action_type='content_review',title='审核发布',params={'content_id':1},assignee_role='reviewer'),ctx,db)
            assert task['created_by']=='7' and set(task)=={'id','module','action_type','title','params','status','created_by','assignee_role','completion_evidence','created_at','updated_at'}
            from app.api.seo_cockpit import stage_review_task
            content=await db.get(SeoContentAsset,1)
            await stage_review_task(db,content,ctx,'approve');await db.commit()
            assert (await db.get(SeoTask,task['id'])).status=='in_progress'
            with pytest.raises(HTTPException):await update_task(task['id'],TaskUpdate(tenant_id=1,site_id=1,status='done'),ctx,db)
            await db.rollback()
            with pytest.raises(HTTPException):await get_task(task['id'],2,1,ctx,db)
            content=await db.get(SeoContentAsset,1);content.status='published';content.published_at=datetime.utcnow();await db.commit()
            result=await update_task(task['id'],TaskUpdate(tenant_id=1,site_id=1,status='done'),ctx,db)
            assert result['completion_evidence']['change_abs']==1 and result['completion_evidence']['source']['content_id']==1
            with pytest.raises(HTTPException):await cancel_task(task['id'],1,1,ctx,db)
    run_database(scenario)

def test_database_approval_queue_reuses_page_snapshot_and_preserves_proof():
    async def scenario(sessions):
        now=datetime.now(timezone.utc)
        async with sessions() as db:
            db.add(SeoSite(id=1,tenant_id=1,tenant_module_id=1,name='brand',domain='brand.example',canonical_domain='brand.example',status='active'))
            db.add(SeoSitePage(id=1,tenant_id=1,site_id=1,url='https://brand.example/article',status='needs_fix'))
            db.add(SeoPageSnapshot(id=1,tenant_id=1,site_id=1,crawl_run_id=1,url='https://brand.example/article',image_alt_evidence=image_alt_evidence(BeautifulSoup('<img src="/a.png">','html.parser'),'https://brand.example/article')))
            review=SeoImageAltReview(id=1,tenant_id=1,site_id=1,page_id=1,snapshot_id=1,position=1,source_url='https://brand.example/a.png',observed_alt_state='missing',decision='informative',alt_suggestion='品牌产品',review_status='approved',actor_id=7,actor_name='test',reviewed_at=now,updated_at=now)
            db.add(review);await enqueue_image_verification(db,review);await db.commit()
            assert (await db.scalar(select(SeoImageVerification))).status=='pending'
            await db.execute(text("SELECT setval(pg_get_serial_sequence('seo_page_snapshots','id'), 1)"))
            await db.execute(text("SELECT setval(pg_get_serial_sequence('seo_crawl_runs','id'), 1)"));await db.commit()
            job=await db.scalar(select(SeoImageVerification))
            job.status='checking';job.available_at=now-timedelta(minutes=6)
            await db.commit()  # Simulate a worker that stopped after claiming.
        values={'url':'https://brand.example/article','discovery_source':'single_page','click_depth':0,'status_code':200,'issue_codes':[],
            'image_alt_evidence':image_alt_evidence(BeautifulSoup('<img src="/a.png" alt="品牌产品">','html.parser'),'https://brand.example/article')}
        with patch('app.seo_image_verification.async_session_factory',sessions),patch('app.module_scope.list_active_module_tenants',new=AsyncMock(return_value=[SimpleNamespace(id=1)])),patch('app.seo_image_verification.collect_page_snapshot',new=AsyncMock(return_value=values)) as fetch:
            await verify_pending_images()
            await verify_pending_images()
            assert fetch.await_count==1
        async with sessions() as db:
            job=await db.scalar(select(SeoImageVerification))
            assert job.status=='verified' and job.result_snapshot_id is not None
            assert job.evidence['before_snapshot_id']==1 and job.evidence['change_abs']==1
            assert (await db.get(SeoPageSnapshot,job.result_snapshot_id)).image_alt_evidence['observations'][0]['alt']=='品牌产品'
    run_database(scenario)
