"""Native source adapter, real DB identities/JWT; no provider or platform calls."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import os
import re
import json
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.schema import CreateTable

from app import seo_distribution_sources as source
from app.api.seo import _content_confirmation_hash
from app.database import get_session
from app.security.auth import issue_token, require_auth
from app.models.user import User
from app.models.role import Role
from app.models.module_workspace import SeoSite, TenantModule
from app.models.seo import (SeoContentAsset, SeoContentConfirmation, SeoDistributionVariant,
    SeoDistributionConnection, SeoSiteAdvisorAssignment, SeoKeywordAsset)
from test_seo_workflow_postgres import database

pytestmark=pytest.mark.skipif(not os.getenv('SEO_WORKFLOW_TEST_DATABASE_URL'),reason='isolated local PostgreSQL required')


@asynccontextmanager
async def fixture():
    async with database() as sessions:
        async with sessions.begin() as db:
            for model in (SeoDistributionConnection,SeoDistributionVariant):
                await db.execute(CreateTable(model.__table__,include_foreign_key_constraints=[]))
            content=SeoContentAsset(id=40,tenant_id=4,site_id=2,content_type='article',title='selection article',
                draft='<p>selection article body</p>',status='ready',version_count=3,keyword_ids=[20],
                reviewed_by=7,reviewed_at=datetime(2026,10,10))
            db.add(content)
            db.add(SeoDistributionConnection(id=50,tenant_id=4,platform_code='wechat_official',name='synthetic',
                mode='manual',enabled=True,status='manual_required'))
            db.add(SeoDistributionVariant(id=60,tenant_id=4,content_asset_id=40,connection_id=50,
                platform_code='wechat_official',source_version=3,revision_number=2,status='approved',
                title='selection article',content='<p>selection article body</p>',reviewed_by=7,reviewed_at=datetime(2026,10,10)))
            db.add(SeoContentConfirmation(id=70,tenant_id=4,site_id=2,content_asset_id=40,
                content_version=3,content_hash=_content_confirmation_hash(content),decision='approve',
                actor_mode='advisor_proxy',actor_user_id=7,actor_role_name='advisor',created_at=datetime(2026,10,10)))
        yield sessions


async def load(db,**values):
    return await source.load_source(db,**({'actor_user_id':7,'tenant_id':4,'scope_id':2,'variant_id':60,
        'platform':'wechat-article'}|values))


async def listing(db, **values):
    return await source.list_sources(db, **({'actor_user_id':7,'tenant_id':4,'scope_id':2,
        'platform':'wechat-article'} | values))


def test_snapshot_readonly_fresh_identities_and_no_flush_or_network(monkeypatch):
    async def forbidden(*args,**kwargs): pytest.fail('Source loading must not call external HTTP')
    monkeypatch.setattr(httpx.AsyncClient,'send',forbidden)
    async def scenario():
        async with fixture() as sessions:
            async with sessions() as db:
                await db.execute(text('SET TRANSACTION READ ONLY'))
                first=await load(db)
                assert set(first)=={'module','tenant_id','scope_id','variant_id','source_revision','content'}
                assert first['source_revision'].startswith('seo-m3-v2-')
                assert re.fullmatch(r'[a-zA-Z0-9_-]{1,128}',first['source_revision'])
                assert first['content']=={'version':first['source_revision'],'title':'selection article',
                    'body':'<p>selection article body</p>','assets':[]}
                assert not db.dirty and not db.new
                assert first==await load(db)
                root=Path(__file__).parents[1]
                evidence={'source':'isolated PostgreSQL synthetic reviewed article; zero platform calls',
                    'backend_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
                    'source_tree_clean':not bool(subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip()),
                    'snapshot':first}
                (Path(os.environ['TEMP'])/'seo-distribution-source-snapshot.json').write_text(
                    json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
            async with sessions() as cached:
                actor=await cached.get(User,7)
                variant=await cached.get(SeoDistributionVariant,60)
                variant.content='client-side injected body'
                assert (await load(cached))==first  # no autoflush, no identity-map substitution
                assert variant.content=='client-side injected body'
                async with sessions.begin() as changed:
                    (await changed.get(User,7)).is_active=False
                assert actor.is_active
                with pytest.raises(HTTPException) as exc: await load(cached)
                assert exc.value.status_code==403
    asyncio.run(scenario())


@pytest.mark.parametrize('change,code',[
    ('inactive','identity_required'),('wrong_customer','identity_required'),('role','advisor_required'),
    ('assignment','advisor_required'),('module','site_unavailable'),('site','site_unavailable'),
    ('paused_plan','site_unavailable'),('content_scope','source_not_found'),('connection_scope','source_not_found'),
    ('expired_module','site_unavailable'),('missing_role','identity_required'),
    ('platform','platform_mismatch'),('connection_disabled','connection_unavailable'),('connection_api','connection_unavailable'),
    ('master_version','source_stale'),('new_draft','source_stale'),('master_review','review_required'),
    ('variant_review','review_required'),('review_actor','review_required'),('review_date','review_required'),
    ('confirmation_missing','confirmation_required'),('confirmation_rejected','confirmation_required'),
    ('confirmation_scope','confirmation_required'),('master_body','confirmation_required'),
    ('keyword_missing','keywords_invalid'),('keyword_scope','keywords_invalid'),('content_type','content_type_unsupported'),
    ('image','assets_unavailable'),('markdown_image','assets_unavailable'),('script','content_invalid'),
])
def test_latest_database_gates_reject_stale_or_unapproved_sources(change,code):
    async def scenario():
        async with fixture() as sessions:
            async with sessions.begin() as db:
                user=await db.get(User,7); content=await db.get(SeoContentAsset,40)
                variant=await db.get(SeoDistributionVariant,60); account=await db.get(SeoDistributionConnection,50)
                approval=await db.get(SeoContentConfirmation,70)
                if change=='inactive': user.is_active=False
                elif change=='wrong_customer': user.tenant_id=9
                elif change=='role': (await db.get(Role,5)).permissions={'seo.content':'view','seo.site':'edit'}
                elif change=='assignment': (await db.get(SeoSiteAdvisorAssignment,3)).active=False
                elif change=='module': (await db.get(TenantModule,1)).status='paused'
                elif change=='expired_module': (await db.get(TenantModule,1)).expires_at=datetime(2020,1,1).date()
                elif change=='missing_role': await db.delete(await db.get(Role,5))
                elif change=='site': (await db.get(SeoSite,2)).status='archived'
                elif change=='paused_plan': (await db.get(SeoSite,2)).site_settings={'seo_service_plan':{'status':'paused'}}
                elif change=='content_scope': content.site_id=9
                elif change=='connection_scope': account.tenant_id=9
                elif change=='platform': account.platform_code='xiaohongshu'
                elif change=='connection_disabled': account.enabled=False
                elif change=='connection_api': account.mode='api'; account.status='unconfigured'
                elif change=='master_version': content.version_count=4
                elif change=='new_draft': db.add(SeoDistributionVariant(id=61,tenant_id=4,content_asset_id=40,connection_id=50,
                    platform_code='wechat_official',source_version=3,revision_number=3,status='draft',title='new',content='new'))
                elif change=='master_review': content.status='review'
                elif change=='variant_review': variant.status='pending_review'
                elif change=='review_actor': variant.reviewed_by=None
                elif change=='review_date': content.reviewed_at=None
                elif change=='confirmation_missing': await db.delete(approval)
                elif change=='confirmation_rejected': db.add(SeoContentConfirmation(id=71,tenant_id=4,site_id=2,content_asset_id=40,
                    content_version=3,content_hash=approval.content_hash,decision='reject',actor_mode='customer_direct',
                    actor_user_id=8,actor_role_name='customer',created_at=datetime(2026,10,11)))
                elif change=='confirmation_scope': approval.site_id=9
                elif change=='master_body': content.draft='changed without version bump'
                elif change=='keyword_missing': variant.content='<p>unrelated text</p>'
                elif change=='keyword_scope': (await db.get(SeoKeywordAsset,20)).site_id=9
                elif change=='content_type': content.content_type='qa'
                elif change=='image': variant.content+='<img src="https://example.com/image.png">'
                elif change=='markdown_image': variant.content='selection ![picture](https://example.com/a.png)'
                elif change=='script': variant.content+='<script>alert(1)</script>'
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc: await load(db)
                assert exc.value.detail['code']=='seo_distribution_'+code
                assert set(exc.value.detail)=={'code','message'}
                if code in {'identity_required','advisor_required','site_unavailable'}:
                    with pytest.raises(HTTPException) as page_error: await listing(db)
                    assert page_error.value.detail['code']=='seo_distribution_'+code
                else:
                    assert await listing(db)==[]
    asyncio.run(scenario())


def test_revision_tracks_reapproval_payload_and_confirmation_identity():
    async def scenario():
        async with fixture() as sessions:
            versions=[]
            for step in range(4):
                async with sessions.begin() as db:
                    variant=await db.get(SeoDistributionVariant,60)
                    if step==1: variant.content='<p>selection updated reviewed body</p>'
                    if step==2: variant.reviewed_at+=timedelta(seconds=1)
                    if step==3: (await db.get(SeoContentConfirmation,70)).created_at+=timedelta(seconds=1)
                async with sessions() as db: versions.append((await load(db))['source_revision'])
            assert len(set(versions))==4
    asyncio.run(scenario())


def test_assets_reserved_unknown_platform_and_invalid_id_rejected():
    async def scenario():
        async with fixture() as sessions:
            async with sessions.begin() as db:
                connection=await db.connection()
                raw=await connection.get_raw_connection()
                await raw.driver_connection.execute((Path(__file__).parents[1]/'scripts/seo_distribution_media_schema.sql').read_text())
                (await db.get(SeoDistributionVariant,60)).platform_code='xiaohongshu'
                (await db.get(SeoDistributionConnection,50)).platform_code='xiaohongshu'
            async with sessions() as db:
                for values,code in [({'platform':'xiaohongshu-image'},'assets_unavailable'),
                    ({'platform':'unknown'},'platform_unsupported'),({'actor_user_id':None},'invalid_scope'),
                    ({'actor_user_id':True},'invalid_scope'),({'variant_id':60.0},'invalid_scope')]:
                    with pytest.raises(HTTPException) as exc: await load(db,**values)
                    assert exc.value.detail['code']=='seo_distribution_'+code
    asyncio.run(scenario())


def test_missing_confirmation_structure_fails_closed_without_ddl():
    async def scenario():
        async with fixture() as sessions:
            async with sessions.begin() as db: await db.execute(text('DROP TABLE seo_content_confirmations'))
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc: await load(db)
                assert exc.value.status_code==503 and exc.value.detail['code']=='seo_distribution_source_unavailable'
    asyncio.run(scenario())


def test_real_jwt_identity_and_current_role_are_not_trusted_from_caller():
    async def scenario():
        async with fixture() as sessions:
            app=FastAPI()
            async def db_dep():
                async with sessions() as db: yield db
            app.dependency_overrides[get_session]=db_dep
            @app.get('/synthetic-source')
            async def endpoint(ctx=Depends(require_auth),db=Depends(get_session)):
                return await load(db,actor_user_id=ctx.user_id)
            async with sessions() as db: token=issue_token(await db.get(User,7))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://synthetic') as client:
                assert (await client.get('/synthetic-source')).status_code==401
                headers={'Authorization':'Bearer '+token}
                assert (await client.get('/synthetic-source',headers=headers)).status_code==200
                async with sessions.begin() as db: (await db.get(Role,5)).permissions={}
                assert (await client.get('/synthetic-source',headers=headers)).status_code==403
    asyncio.run(scenario())


def test_scope_authorization_needs_no_content_tables_and_rejects_wrong_assignment():
    async def scenario():
        async with fixture() as sessions:
            async with sessions.begin() as db:
                await db.execute(text('DROP TABLE seo_distribution_variants'))
            async with sessions() as db:
                await db.execute(text('SET TRANSACTION READ ONLY'))
                assert await source.authorize_scope(db,7,4,2) is None
                for actor,tenant,scope in [(999,4,2),(7,9,2),(7,4,9)]:
                    with pytest.raises(HTTPException) as exc: await source.authorize_scope(db,actor,tenant,scope)
                    assert exc.value.status_code in {403,404}
            async with sessions.begin() as db:
                (await db.get(SeoSiteAdvisorAssignment,3)).active=False
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc: await source.authorize_scope(db,7,4,2)
                assert exc.value.detail['code']=='seo_distribution_advisor_required'
    asyncio.run(scenario())


def test_body_query_never_runs_before_scope_authorization(monkeypatch):
    async def forbidden(*args,**kwargs): pytest.fail('Unauthorised caller reached the body query')
    monkeypatch.setattr(source,'_load',forbidden)
    async def scenario():
        async with fixture() as sessions:
            async with sessions.begin() as db: (await db.get(Role,5)).permissions={}
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc: await load(db)
                assert exc.value.status_code==403
    asyncio.run(scenario())


@pytest.mark.parametrize('error',[OSError,TimeoutError])
def test_database_transport_errors_have_only_fixed_safe_details(error,monkeypatch):
    async def fail(*args,**kwargs): raise error('synthetic private connection details')
    async def scenario():
        async with fixture() as sessions:
            async with sessions() as db:
                monkeypatch.setattr(db,'execute',fail)
                for call in (lambda:source.authorize_scope(db,7,4,2),lambda:load(db),lambda:listing(db)):
                    with pytest.raises(HTTPException) as exc: await call()
                    assert exc.value.status_code==503
                    assert exc.value.detail=={'code':'seo_distribution_source_unavailable',
                        'message':'来源结构或数据库暂不可用，请稍后核对'}
    asyncio.run(scenario())


def test_listing_is_readonly_summary_only_and_ignores_pending_body(monkeypatch):
    async def forbidden(*args,**kwargs): pytest.fail('Listing must not call external HTTP')
    monkeypatch.setattr(httpx.AsyncClient,'send',forbidden)
    async def scenario():
        async with fixture() as sessions:
            async with sessions() as db:
                await db.execute(text('SET TRANSACTION READ ONLY'))
                variant=await db.get(SeoDistributionVariant,60)
                variant.content='uncommitted private client text'
                snapshot=await load(db)
                assert await listing(db)==[{'variant_id':60,'source_revision':snapshot['source_revision'],
                    'title':'selection article','platform':'wechat-article'}]
                assert variant.content=='uncommitted private client text'
                assert variant in db.dirty
    asyncio.run(scenario())


def test_listing_selects_latest_approved_and_never_falls_back_to_old_review():
    async def scenario():
        async with fixture() as sessions:
            async with sessions.begin() as db:
                db.add(SeoDistributionVariant(id=61,tenant_id=4,content_asset_id=40,connection_id=50,
                    platform_code='wechat_official',source_version=3,revision_number=3,status='approved',
                    title='selection latest',content='<p>selection latest body</p>',
                    reviewed_by=7,reviewed_at=datetime(2026,10,11)))
            async with sessions() as db:
                rows=await listing(db)
                assert len(rows)==1 and rows[0]['variant_id']==61 and rows[0]['title']=='selection latest'
            async with sessions.begin() as db:
                (await db.get(SeoDistributionVariant,61)).status='pending_review'
            async with sessions() as db: assert await listing(db)==[]
    asyncio.run(scenario())


def test_listing_bounds_candidates_at_50_before_source_loading(monkeypatch):
    seen=[]
    original=source.load_source
    async def tracked(session,actor,tenant,scope,variant,platform):
        seen.append(variant)
        return await original(session,actor,tenant,scope,variant,platform)
    monkeypatch.setattr(source,'load_source',tracked)
    async def scenario():
        async with fixture() as sessions:
            async with sessions.begin() as db:
                # Fix all timestamps so wall-clock time cannot move fixture 60
                # ahead of the explicitly dated rows under test.
                (await db.get(SeoDistributionVariant,60)).updated_at=datetime(2026,10,12)
                for number in range(55):
                    db.add(SeoDistributionConnection(id=100+number,tenant_id=4,platform_code='wechat_official',
                        name=f'synthetic-{number}',mode='manual',enabled=True,status='manual_required'))
                    db.add(SeoDistributionVariant(id=200+number,tenant_id=4,content_asset_id=40,
                        connection_id=100+number,platform_code='wechat_official',source_version=3,
                        revision_number=1,status='approved',title='selection article',content='<p>selection body</p>',
                        reviewed_by=7,reviewed_at=datetime(2026,10,11),updated_at=datetime(2026,10,12)))
            async with sessions() as db:
                await db.execute(text('SET TRANSACTION READ ONLY'))
                rows=await listing(db)
                assert len(rows)==50 and len(seen)==50 and len(set(seen))==50
                assert seen==sorted(seen,reverse=True)
    asyncio.run(scenario())


@pytest.mark.parametrize('values', [{'actor_user_id':999},{'tenant_id':9},{'scope_id':9}])
def test_listing_rejects_scope_before_candidate_selection(values):
    async def scenario():
        async with fixture() as sessions:
            async with sessions.begin() as db: await db.execute(text('DROP TABLE seo_distribution_variants'))
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc: await listing(db,**values)
                assert exc.value.status_code in {403,404}
    asyncio.run(scenario())


def test_listing_explicitly_reserves_images_and_rejects_unknown_platform():
    async def scenario():
        async with fixture() as sessions:
            async with sessions() as db:
                assert await listing(db,platform='xiaohongshu-image')==[]
                for platform,code in [('unknown','platform_unsupported')]:
                    with pytest.raises(HTTPException) as exc: await listing(db,platform=platform)
                    assert exc.value.detail['code']=='seo_distribution_'+code
    asyncio.run(scenario())


@pytest.mark.parametrize('code,status', [('advisor_required',403),('scope_not_found',404),
    ('source_not_found',404),('site_unavailable',409),('source_unavailable',503)])
def test_listing_never_swallows_identity_scope_or_database_failure(code,status,monkeypatch):
    async def rejected(*args,**kwargs): raise source.denied(code,'fixed synthetic error',status)
    monkeypatch.setattr(source,'load_source',rejected)
    async def scenario():
        async with fixture() as sessions:
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc: await listing(db)
                assert exc.value.status_code==status and exc.value.detail['code']=='seo_distribution_'+code
    asyncio.run(scenario())


def test_listing_rechecks_scope_after_loading_before_return(monkeypatch):
    original=source.load_source
    async def scenario():
        async with fixture() as sessions:
            async def revoke_after_loading(*args,**kwargs):
                snapshot=await original(*args,**kwargs)
                async with sessions.begin() as changed: (await changed.get(SeoSiteAdvisorAssignment,3)).active=False
                return snapshot
            monkeypatch.setattr(source,'load_source',revoke_after_loading)
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc: await listing(db)
                assert exc.value.detail['code']=='seo_distribution_advisor_required'
    asyncio.run(scenario())


def test_listing_missing_source_structure_fails_closed():
    async def scenario():
        async with fixture() as sessions:
            async with sessions.begin() as db: await db.execute(text('DROP TABLE seo_distribution_variants'))
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc: await listing(db)
                assert exc.value.status_code==503
                assert exc.value.detail['code']=='seo_distribution_source_unavailable'
    asyncio.run(scenario())
