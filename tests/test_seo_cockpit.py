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
from app.seo_image_verification import (
    complete_image_verification_evidence,evaluate_image_repair,enqueue_image_verification,
    prepare_image_verification_retry,verify_pending_images,
)
from app.models.seo_cockpit import SeoTask,SeoImageVerification
from app.models.seo import SeoSitePage,SeoImageAltReview,SeoPageSnapshot,SeoCrawlRun,SeoKeywordAsset,SeoRankSnapshot,SeoContentAsset,SeoMetricSnapshot
from app.models.module_workspace import SeoSite,TenantModule
from app.models.seo import SeoBacklink
from app.security.auth import AuthContext
from app.api.seo_cockpit import (
    TaskCreate,TaskUpdate,create_task,update_task,get_task,cancel_task,
    backlink_queue_item,image_queue_item,page_queue_item,publication_queue_item,retry_image_verification,
)

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
                for model in [TenantModule,SeoSite,SeoSitePage,SeoImageAltReview,SeoPageSnapshot,SeoCrawlRun,SeoTask,SeoImageVerification,SeoKeywordAsset,SeoRankSnapshot,SeoContentAsset,SeoMetricSnapshot,SeoBacklink]:
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
            db.add(TenantModule(id=1,tenant_id=1,module_code='seo',status='active'))
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
            assert job.evidence['attempt']==1 and job.evidence['attempt_history']==[]
            assert (await db.get(SeoPageSnapshot,job.result_snapshot_id)).image_alt_evidence['observations'][0]['alt']=='品牌产品'
    run_database(scenario)


def test_image_worker_does_not_fetch_after_site_becomes_inactive():
    async def scenario(sessions):
        now=datetime.now(timezone.utc)
        async with sessions() as db:
            db.add(TenantModule(id=1,tenant_id=1,module_code='seo',status='active'))
            db.add(SeoSite(id=1,tenant_id=1,tenant_module_id=1,name='brand',domain='brand.example',canonical_domain='brand.example',status='active'))
            db.add(SeoSitePage(id=1,tenant_id=1,site_id=1,url='https://brand.example/article',status='needs_fix'))
            db.add(SeoImageAltReview(id=1,tenant_id=1,site_id=1,page_id=1,snapshot_id=1,position=1,source_url='https://brand.example/a.png',observed_alt_state='missing',decision='informative',alt_suggestion='品牌产品',review_status='approved',actor_id=7,actor_name='test',reviewed_at=now,updated_at=now))
            db.add(SeoImageVerification(id=1,tenant_id=1,site_id=1,page_id=1,review_id=1,status='pending',approved_at=now,available_at=now))
            await db.commit()
        fetch=AsyncMock()
        with patch('app.seo_image_verification.async_session_factory',sessions),patch('app.module_scope.list_active_module_tenants',new=AsyncMock(return_value=[SimpleNamespace(id=1)])),patch('app.module_scope.seo_site_is_operational',new=AsyncMock(return_value=False)),patch('app.seo_image_verification.collect_page_snapshot',new=fetch):
            await verify_pending_images()
        fetch.assert_not_awaited()

    run_database(scenario)


def _queue_row(**values):
    now = datetime(2026, 9, 11, tzinfo=timezone.utc)
    defaults = dict(id=1, tenant_id=3, site_id=7, updated_at=now, created_at=now, checked_at=None, last_checked_at=None)
    defaults.update(values)
    return SimpleNamespace(**defaults)


def test_image_retry_preserves_bounded_attempt_history_and_actor():
    now=datetime(2026,9,11,8,30,tzinfo=timezone.utc)
    old_history=[{'attempt':value,'status':'unavailable'} for value in range(1,21)]
    verification=_queue_row(status='unverified',checked_at=now-timedelta(minutes=10),result_snapshot_id=81,
        evidence={'attempt':21,'attempt_history':old_history,'reason':'新 Alt 尚未生效','before_snapshot_id':10,
                  'after_snapshot_id':81,'change_abs':0})
    pending=prepare_image_verification_retry(verification,now,actor_id=17)
    assert pending['attempt']==22 and len(pending['attempt_history'])==20
    assert pending['attempt_history'][-1]=={'attempt':21,'status':'unverified','checked_at':(now-timedelta(minutes=10)).isoformat(),
        'result_snapshot_id':81,'reason':'新 Alt 尚未生效','before_snapshot_id':10,'after_snapshot_id':81,'change_abs':0}
    assert pending['retry_request']=={'requested_at':now.isoformat(),'requested_by':'17','from_status':'unverified'}
    completed=complete_image_verification_evidence(pending,{'reason':'重新抓取已确认','change_abs':1},1,81,82)
    assert completed['attempt']==22 and completed['attempt_history']==pending['attempt_history']
    assert completed['retry_request']==pending['retry_request']
    assert completed['before_snapshot_id']==81 and completed['after_snapshot_id']==82


def test_image_retry_endpoint_records_actor_before_requeue():
    now=datetime.now(timezone.utc)
    verification=_queue_row(status='unavailable',checked_at=now-timedelta(minutes=10),result_snapshot_id=9,
        evidence={'attempt':1,'reason':'timeout','before_snapshot_id':1,'after_snapshot_id':9,'change_abs':0})
    session=SimpleNamespace(get=AsyncMock(return_value=verification),commit=AsyncMock())
    ctx=SimpleNamespace(user_id=17)

    async def run():
        with patch('app.api.seo_cockpit.scope',new=AsyncMock()):
            result=await retry_image_verification(1,3,7,ctx,session)
        assert result['status']=='pending' and result['attempt']==2
        assert result['retry_request']['requested_by']=='17'
        assert verification.status=='pending' and verification.evidence['attempt_history'][-1]['status']=='unavailable'
        session.commit.assert_awaited_once()

    asyncio.run(run())


def test_customer_verification_image_requires_crawl_evidence_before_verified():
    readonly = image_queue_item(_queue_row(status='unverified', page_id=8, evidence={'actual_alt': ''}))
    assert readonly['state'] == 'pending_customer_action'
    assert readonly['can_retry'] is False and 'retry_action' not in readonly
    assert '查看权限' in readonly['retry_reason']
    assert image_queue_item(_queue_row(status='pending', page_id=8, evidence=None))['state'] == 'pending_system_check'
    assert image_queue_item(_queue_row(status='verified', page_id=8, evidence={'actual_alt': '减速机'}))['state'] == 'verified'
    unavailable = image_queue_item(_queue_row(status='unavailable', page_id=8, evidence={'error': 'timeout'}),allow_retry=True)
    assert unavailable['state'] == 'failed_retry'
    assert unavailable['can_retry'] is True
    assert unavailable['retry_action'] == {'method':'POST','url':'/api/v1/seo/image-verifications/1/retry','verification_id':1,'tenant_id':3,'site_id':7}
    unverified = image_queue_item(_queue_row(status='unverified', page_id=8, evidence={'actual_alt': ''}),allow_retry=True)
    assert unverified['can_retry'] is True and unverified['retry_action']['verification_id'] == 1


def test_customer_verification_publication_draft_is_not_verified():
    now = datetime(2026, 9, 11, tzinfo=timezone.utc)
    base = dict(platform_name='知乎', adapted_title='选型指南', published_at=now, last_error=None)
    assert publication_queue_item(_queue_row(status='manual_required', page_url=None, link_discovery=None, **base))['state'] == 'pending_customer_action'
    assert publication_queue_item(_queue_row(status='draft_created', page_url='https://draft.example/1', link_discovery={'state':'readable'}, **base))['state'] == 'pending_customer_action'
    assert publication_queue_item(_queue_row(status='published', page_url='https://zhuanlan.zhihu.com/p/1', link_discovery=None, **base))['state'] == 'pending_system_check'
    assert publication_queue_item(_queue_row(status='published', page_url='https://zhuanlan.zhihu.com/p/1', link_discovery={'state':'readable','found':0}, **base))['state'] == 'verified'
    assert publication_queue_item(_queue_row(status='failed', page_url=None, link_discovery=None, **base))['state'] == 'failed_retry'


def test_customer_verification_publication_includes_sanitized_latest_attempt_provenance():
    started=datetime(2026,9,11,7,30,tzinfo=timezone.utc)
    completed=started+timedelta(seconds=8)
    attempt=SimpleNamespace(id=42,action='manual_complete',status='succeeded',created_by=17,
        started_at=started,completed_at=completed,request_summary={'secret':'must-not-leak'},
        response_summary={'remote_payload':'must-not-leak'},error='raw provider error')
    row=_queue_row(status='published',platform_name='知乎',adapted_title='选型指南',published_at=completed,
        page_url='https://zhuanlan.zhihu.com/p/1',link_discovery=None,last_error=None)
    item=publication_queue_item(row,attempt)
    assert item['state']=='pending_system_check'
    assert item['evidence']=={'page_url':'https://zhuanlan.zhihu.com/p/1','published_at':completed,'link_discovery':None,
        'latest_attempt':{'id':42,'action':'manual_complete','status':'succeeded',
        'created_by':17,'started_at':started,'completed_at':completed}}
    assert 'request_summary' not in str(item['evidence']) and 'raw provider error' not in str(item['evidence'])


def test_customer_verification_page_and_backlink_use_observed_state():
    assert page_queue_item(_queue_row(status='approved', url='https://example.cn/a', title='A', http_status=200, audit_score=80, issue_codes=[], last_error=None))['state'] == 'pending_customer_action'
    assert page_queue_item(_queue_row(status='implemented', url='https://example.cn/a', title='A', http_status=200, audit_score=80, issue_codes=[], last_error=None))['state'] == 'pending_system_check'
    assert page_queue_item(_queue_row(status='verified', url='https://example.cn/a', title='A', http_status=200, audit_score=100, issue_codes=[], last_error=None))['state'] == 'verified'
    link = dict(status='active', source_url='https://source.cn/a', target_url='https://example.cn/a', source_domain='source.cn')
    assert backlink_queue_item(_queue_row(verification={'state':'found'}, **link))['state'] == 'verified'
    assert backlink_queue_item(_queue_row(verification={'state':'pending'}, **link))['state'] == 'pending_system_check'
    assert backlink_queue_item(_queue_row(verification={'state':'missing'}, **link))['state'] == 'failed_retry'
