from datetime import datetime,timedelta,timezone
import pytest
from fastapi import HTTPException
from app.api.seo_backlink_workflow import usage
from app.api.seo_cockpit import TaskCreate,TaskUpdate,create_task,update_task
from app.models.module_workspace import SeoSite
from app.models.seo import SeoBacklink
from app.security.auth import AuthContext
from test_seo_cockpit import run_database

def test_failed_and_running_queries_consume_budget_even_after_domain_change():
    now=datetime.now(timezone.utc)
    settings={'backlink_index':{'state':'failed','domain':'old.example','attempted_at':now.isoformat()},
        'backlink_opportunities':{'state':'running','attempted_at':now.isoformat(),'max_provider_calls':3}}
    result=usage(settings,now)
    assert [row['reserved_calls'] for row in result['quotas']]==[1,3]
    assert all(row['remaining_calls']==0 for row in result['quotas'])
    assert result['cost'] is None
    assert all(row['reserved_calls']==0 for row in usage(settings,now+timedelta(days=2))['quotas'])

def test_backlink_followup_requires_new_verified_link_and_metric_growth():
    async def scenario(sessions):
        ctx=AuthContext(7,'test','operator',1,{'seo.links':'edit'})
        async with sessions() as db:
            db.add(SeoSite(id=1,tenant_id=1,tenant_module_id=1,name='brand',domain='brand.example',canonical_domain='brand.example',status='active'))
            await db.commit()
            args={'tenant_id':1,'site_id':1,'action_type':'backlink_outreach','title':'合作跟进','assignee_role':'seo_operator'}
            with pytest.raises(HTTPException):await create_task(TaskCreate(**args,params={'source_url':'https://brand.example/page'}),ctx,db)
            task=await create_task(TaskCreate(**args,params={'source_url':'https://publisher.example/article'}),ctx,db)
            result=await update_task(task['id'],TaskUpdate(tenant_id=1,site_id=1,note='已完成来源评估',status='in_progress'),ctx,db)
            assert result['params']['followups'][0]['actor']=='7'
            with pytest.raises(HTTPException):await update_task(task['id'],TaskUpdate(tenant_id=1,site_id=1,status='done'),ctx,db)
            await db.rollback()
            link=SeoBacklink(id=1,tenant_id=1,site_id=1,source_url='https://publisher.example/new',target_url='https://brand.example/',source_domain='publisher.example',status='active',verification={'state':'pending'},first_seen_at=datetime.utcnow(),last_checked_at=datetime.utcnow())
            db.add(link);await db.commit()
            with pytest.raises(HTTPException):await update_task(task['id'],TaskUpdate(tenant_id=1,site_id=1,status='done'),ctx,db)
            await db.rollback()
            link=await db.get(SeoBacklink,1);link.verification={'state':'found'};await db.commit()
            result=await update_task(task['id'],TaskUpdate(tenant_id=1,site_id=1,status='done'),ctx,db)
            assert result['completion_evidence']['source']['backlink_id']==1
            assert result['completion_evidence']['change_abs']==1
            with pytest.raises(HTTPException):await update_task(task['id'],TaskUpdate(tenant_id=1,site_id=1,note='不能改历史'),ctx,db)
    run_database(scenario)
