"""Native row-lock/admission regression, only in an explicitly scoped local DB."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.schema import CreateTable

from app import api_controls as controls, api_metering as meter, seo_backlink_sources as backlinks
from app.api import seo, seo_site_diagnostics as images
from app.models.module_workspace import SeoSite
from app.models.seo import SeoSitePage, SeoPageSnapshot, SeoImageAltReview, SeoBacklink, SeoKeywordAsset
from app.models.seo_cockpit import SeoImageVerification
from app.security.auth import AuthContext

pytestmark = pytest.mark.skipif(not os.getenv('SEO_USAGE_TEST_DATABASE_URL'), reason='requires isolated local PostgreSQL')
ACTOR = AuthContext(7, 'reviewer', 'editor', 1, {'seo.site':'edit', 'seo.links':'edit'})


@asynccontextmanager
async def database():
    url = make_url(os.environ['SEO_USAGE_TEST_DATABASE_URL'])
    assert url.drivername == 'postgresql+asyncpg' and url.host == '127.0.0.1' and url.port == 55432
    assert (url.database, url.username) == ('seo_workflow_test', 'seo_workflow_tester') and not url.query
    schema = 'seo_review_test_' + uuid4().hex
    engine = create_async_engine(url, connect_args={'server_settings': {'search_path':schema, 'statement_timeout':'10000'}})
    created = False
    try:
        async with engine.begin() as conn:
            assert await conn.scalar(text('SELECT current_database()')) == 'seo_workflow_test'
            assert await conn.scalar(text('SELECT current_user')) == 'seo_workflow_tester'
            assert not await conn.scalar(text('SELECT rolsuper FROM pg_roles WHERE rolname=current_user'))
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
            assert await conn.scalar(text('SELECT current_schema()')) == schema
            for model in (SeoSite, SeoSitePage, SeoPageSnapshot, SeoImageAltReview, SeoImageVerification, SeoBacklink, SeoKeywordAsset):
                await conn.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
            native = await conn.get_raw_connection()
            await native.driver_connection.execute((Path(__file__).parent/'fixtures/seo_api_controls.sql').read_text())
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            session.add(SeoSite(id=1, tenant_id=1, tenant_module_id=1, name='fixture', domain='example.com', canonical_domain='example.com', status='active'))
            for ident in (10,20):
                url = f'https://example.com/page/{ident}'
                session.add(SeoSitePage(id=ident, tenant_id=1, site_id=1, url=url, status='needs_fix'))
                session.add(SeoPageSnapshot(id=ident, tenant_id=1, site_id=1, crawl_run_id=ident,
                    url=url, status_code=200, fetched_at=datetime(2026,10,10), image_alt_evidence={'items':[
                        {'position':1,'source_url':'https://example.com/image.png','source_attribute':'src',
                         'section':'main','in_link':False,'alt_state':'missing'}]}))
            await session.commit()
        yield sessions
    finally:
        if created:
            assert schema.startswith('seo_review_test_') and len(schema)==48
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


def update_request(**changes):
    return images.ImageAltReviewUpdate(**dict(tenant_id=1,site_id=1,page_id=10,expected_snapshot_id=10,
        expected_review_id=None,expected_review_version=None,position=1,decision='informative',
        alt_suggestion='initial',review_status='draft') | changes)


def test_keyword_move_committing_while_delete_waits_rejects_old_site_and_cached_row():
    async def run():
        async with database() as sessions:
            async with sessions() as seed:
                seed.add(SeoKeywordAsset(id=1,tenant_id=1,site_id=1,keyword='fixture'))
                await seed.commit()
            async with sessions() as mover, sessions() as deleter:
                cached = await deleter.get(SeoKeywordAsset,1)
                row = await mover.get(SeoKeywordAsset,1,with_for_update=True)
                row.site_id=2
                await mover.flush()
                ctx=AuthContext(7,'reviewer','editor',1,{'seo.keywords':'edit'})
                operation=asyncio.create_task(seo.delete_seo_keyword(1,1,deleter,ctx,site_id=1))
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(asyncio.shield(operation),0.05)
                await mover.commit()
                with pytest.raises(HTTPException) as exc: await asyncio.wait_for(operation,5)
                assert exc.value.status_code==404
                assert cached.site_id==2  # FOR UPDATE refreshed the old identity-map value.
                await deleter.rollback()
            async with sessions() as session:
                assert (await session.get(SeoKeywordAsset,1)).site_id==2
    asyncio.run(run())


def test_concurrent_create_update_and_loaded_identity_reject_stale_without_queue_writes():
    async def run():
        async with database() as sessions:
            async def save(request):
                async with sessions() as session:
                    try:
                        return await images.save_image_remediation(request, ACTOR, session)
                    except HTTPException as exc:
                        await session.rollback()
                        return exc.status_code
            results = await asyncio.gather(save(update_request()),save(update_request()))
            assert sorted(isinstance(r,dict) for r in results) == [False,True] and 409 in results
            first = next(r for r in results if isinstance(r,dict))
            req = update_request(expected_review_id=first['id'],expected_review_version=first['version'],review_status='approved')
            results = await asyncio.gather(save(req),save(req.model_copy(update={'alt_suggestion':'other edit'})))
            assert 409 in results
            current = next(r for r in results if isinstance(r,dict))
            assert current['version'] != first['version']
            async with sessions() as stale_session:
                # Exercise SQLAlchemy's identity cache, not only fresh HTTP sessions.
                stale_row = await stale_session.get(SeoImageAltReview,current['id'])
                stale_request = update_request(expected_review_id=current['id'],expected_review_version=current['version'],review_status='approved')
                changed = await save(stale_request.model_copy(update={'alt_suggestion':'newest'}))
                with pytest.raises(HTTPException) as exc:
                    await images.save_image_remediation(stale_request,ACTOR,stale_session)
                assert exc.value.status_code == 409
                await stale_session.rollback()
            async with sessions() as session:
                row = await session.get(SeoImageAltReview,current['id'])
                assert row.alt_suggestion == 'newest' and images.image_review_payload(row)['version'] == changed['version']
                jobs = list(await session.scalars(select(SeoImageVerification)))
                assert len(jobs)==2 and sorted(j.status for j in jobs)==['pending','superseded']
    asyncio.run(run())


def test_reuse_stale_preview_and_source_lock_conflict_do_not_create_drafts():
    async def run():
        async with database() as sessions:
            async with sessions() as session:
                original = await images.save_image_remediation(update_request(review_status='approved'),ACTOR,session)
                preview = await images.preview_cross_page_image_remediation_reuse(1,1,20,ACTOR,session)
            req = images.ImageAltReviewReuse(tenant_id=1,site_id=1,page_id=20,expected_snapshot_id=20,
                                            expected_reuse_version=preview['reuse_version'])
            async with sessions() as holder, sessions() as writer:
                await holder.scalar(select(SeoImageAltReview).where(SeoImageAltReview.id==original['id']).with_for_update())
                with pytest.raises(HTTPException) as exc:
                    await images.reuse_cross_page_image_remediation(req,ACTOR,writer)
                assert exc.value.status_code==409
                await holder.rollback()
            async with sessions() as session:
                await images.save_image_remediation(update_request(expected_review_id=original['id'],expected_review_version=original['version'],
                    alt_suggestion='changed source',review_status='approved'),ACTOR,session)
            async with sessions() as session:
                with pytest.raises(HTTPException) as exc: await images.reuse_cross_page_image_remediation(req,ACTOR,session)
                assert exc.value.status_code==409
                await session.rollback()
                assert await session.scalar(select(func.count()).select_from(SeoImageAltReview).where(SeoImageAltReview.page_id==20)) == 0
                preview = await images.preview_cross_page_image_remediation_reuse(1,1,20,ACTOR,session)
                result = await images.reuse_cross_page_image_remediation(req.model_copy(update={'expected_reuse_version':preview['reuse_version']}),ACTOR,session)
                assert result['copied']==1 and result['review_status']=='draft'
    asyncio.run(run())


def test_copy_requires_reviewed_source_version_and_never_copies_approval():
    async def run():
        async with database() as sessions:
            async with sessions() as session:
                await images.save_image_remediation(update_request(review_status='approved'),ACTOR,session)
                old = await session.get(SeoPageSnapshot,10)
                session.add(SeoPageSnapshot(id=30,tenant_id=1,site_id=1,crawl_run_id=30,url=old.url,
                    fetched_at=datetime(2026,10,11),image_alt_evidence=old.image_alt_evidence,status_code=200))
                await session.commit()
                history = await images.list_image_remediation_history(1,1,10,None,20,ACTOR,session)
                version = next(r['approved_version'] for r in history['items'] if r['snapshot_id']==10)
            request = images.ImageAltReviewCopy(tenant_id=1,site_id=1,page_id=10,expected_snapshot_id=30,
                source_snapshot_id=10,expected_source_version='0'*64)
            async with sessions() as session:
                with pytest.raises(HTTPException) as exc: await images.copy_image_remediation(request,ACTOR,session)
                assert exc.value.status_code==409
                await session.rollback()
                assert await session.scalar(select(func.count()).select_from(SeoImageAltReview))==1
                result=await images.copy_image_remediation(request.model_copy(update={'expected_source_version':version}),ACTOR,session)
                assert result['copied']==1 and result['review_status']=='draft'
                assert await session.scalar(select(func.count()).select_from(SeoImageVerification))==1
    asyncio.run(run())


def test_ai_revalidates_absence_after_human_edit_and_valid_ai_draft_is_reviewable(monkeypatch):
    async def run():
        async with database() as sessions:
            entered,release=asyncio.Event(),asyncio.Event()
            async def reserve(session,tenant_id,**kwargs):
                await session.commit()
                return ('synthetic','lease')
            async def settle(session,tenant_id,reservation,**kwargs):
                await session.commit()
                return True
            async def provider(items):
                entered.set();await release.wait()
                return {'20:20:1':{'alt_suggestion':'AI suggestion','reason':'text evidence'}}
            monkeypatch.setattr(images,'reserve_ai_usage',reserve);monkeypatch.setattr(images,'settle_ai_usage',settle)
            monkeypatch.setattr(images,'generate_alt_drafts',provider)
            req=images.ImageAltAiDraftRequest(tenant_id=1,site_id=1,items=[dict(page_id=20,expected_snapshot_id=20,
                position=1,expected_review_id=None,expected_review_version=None)])
            async def generate():
                async with sessions() as session: return await images.generate_image_alt_drafts(req,ACTOR,session)
            active=asyncio.create_task(generate())
            await asyncio.wait_for(entered.wait(),5)
            async with sessions() as session:
                manual=await images.save_image_remediation(update_request(page_id=20,expected_snapshot_id=20,
                    alt_suggestion='human text',review_status='approved'),ACTOR,session)
            release.set()
            result=await active
            assert result['generated']==0 and result['skipped_changed']==1
            async with sessions() as session:
                row=await session.get(SeoImageAltReview,manual['id'])
                assert row.alt_suggestion=='human text' and images.image_review_payload(row)['version']==manual['version']
            # No external call at all when the originally-empty selection is stale.
            provider_mock=AsyncMock();monkeypatch.setattr(images,'generate_alt_drafts',provider_mock)
            with pytest.raises(HTTPException) as exc: await generate()
            assert exc.value.status_code==409;provider_mock.assert_not_awaited()
            req.items[0]=req.items[0].model_copy(update={'page_id':10,'expected_snapshot_id':10})
            provider_mock.return_value={'10:10:1':{'alt_suggestion':'AI text','reason':'text evidence'}}
            assert (await generate())['generated']==1
            async with sessions() as session:
                row=await session.scalar(select(SeoImageAltReview).where(SeoImageAltReview.page_id==10))
                assert row.review_status=='draft'
                reviewed=await images.save_image_remediation(update_request(expected_review_id=row.id,
                    expected_review_version=images.image_review_payload(row)['version'],review_status='approved'),ACTOR,session)
                assert reviewed['verification_status']=='pending'
    asyncio.run(run())


def test_backlink_admission_concurrency_supplier_errors_and_unknown_results(monkeypatch):
    async def run():
        async with database() as sessions:
            monkeypatch.setattr(meter,'async_session_factory',sessions)
            monkeypatch.setattr(controls,'async_session_factory',sessions)
            monkeypatch.setenv('API_METERING_ENABLED','true');monkeypatch.setenv('API_CONTROLS_ENABLED','true')
            monkeypatch.setattr(backlinks,'get_settings',lambda:SimpleNamespace(seo_backlink_index_enabled=True,
                seo_dataforseo_login='synthetic',seo_dataforseo_password='synthetic'))
            monkeypatch.setattr(seo,'_seo_site',AsyncMock())  # Existing module entitlement is outside this regression.
            calls=[];entered=asyncio.Event();release=asyncio.Event();mode='success'
            async def provider(request):
                calls.append(request)
                entered.set()
                if mode=='success': await release.wait()
                if mode=='timeout': raise httpx.ReadTimeout('synthetic timeout')
                if mode=='bad_json': return httpx.Response(200,text='not-json')
                if mode=='http_error': return httpx.Response(503,text='unavailable')
                return httpx.Response(200,json={'status_code':20000,'tasks':[{'status_code':40501 if mode=='error' else 20000,
                    'result':[{'items':[]}]}]})
            original=httpx.AsyncClient
            monkeypatch.setattr(backlinks.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(provider),**kw))
            async def policy(key,kind,value):
                async with sessions() as session:
                    await session.execute(text('INSERT INTO api_control_settings(key,kind,value,revision,updated_by) VALUES(:k,:t,CAST(:v AS jsonb),1,7) ON CONFLICT(key) DO UPDATE SET value=excluded.value'),{'k':key,'t':kind,'v':json.dumps(value)})
                    await session.commit()
            async def reset_slot():
                async with sessions() as session:
                    site=await session.get(SeoSite,1);site.site_settings={};await session.commit()
            async def query():
                async with sessions() as session: return await seo.query_backlink_index(seo.BacklinkScope(tenant_id=1,site_id=1),session,ACTOR)
            await policy('provider:api.dataforseo.com','provider',{'enabled':False})
            with pytest.raises(controls.ControlDenied): await query()
            assert not calls
            async with sessions() as session:
                assert not (await session.get(SeoSite,1)).site_settings.get('backlink_index')
                assert await session.scalar(text('SELECT count(*) FROM api_usage_events'))==0
            await policy('provider:api.dataforseo.com','provider',{'enabled':True})
            budget=dict(daily_calls=0,monthly_calls=None,daily_cny=None,monthly_cny=None,warning_percent=80)
            # No price and then insufficient money must both deny before HTTP.
            await policy('budget:tenant:1','budget',{**budget,'daily_calls':None,'daily_cny':'1'})
            with pytest.raises(controls.ControlDenied): await query()
            rate_key='rate:api.dataforseo.com:api.dataforseo.com/v3/backlinks/backlinks/live'
            await policy(rate_key,'rate',dict(unit='request',per_request='0.01',version='test-v1',currency='CNY'))
            await policy('budget:tenant:1','budget',{**budget,'daily_calls':None,'daily_cny':'0.001'})
            with pytest.raises(controls.ControlDenied): await query()
            assert not calls
            async with sessions() as session:
                await session.execute(text('DELETE FROM api_control_settings WHERE key=:key'),{'key':rate_key})
                await session.commit()
            await policy('budget:tenant:1','budget',budget)
            with pytest.raises(controls.ControlDenied): await query()
            assert not calls
            await policy('budget:tenant:1','budget',{**budget,'daily_calls':1})
            active=asyncio.create_task(query())
            await asyncio.wait_for(entered.wait(),5)
            cached=await query()
            assert cached['state']=='running' and cached['cached']
            release.set()
            assert (await active)['state']=='completed' and len(calls)==1
            async with sessions() as session:
                event=(await session.execute(text('SELECT * FROM api_usage_events'))).mappings().one()
                assert (event['tenant_id'],event['user_id'],event['module'],event['origin'])==(1,7,'seo','interactive')
                assert event['job_ref'].startswith('site:1:backlink:') and event['state']=='succeeded'
                assert event['estimated_amount'] is None  # Unpriced is not free.
            await reset_slot()
            with pytest.raises(controls.ControlDenied): await query()
            assert len(calls)==1
            await policy('budget:tenant:1','budget',{**budget,'daily_calls':10})
            for mode,expected in [('error','failed'),('timeout','unknown'),('bad_json','unknown'),('http_error','failed')]:
                await reset_slot()
                result=await query()
                assert result['state']==expected and not result['cached']
                before=len(calls)
                assert (await query())['cached'] and len(calls)==before
            async with sessions() as session:
                events=list((await session.execute(text('SELECT state,estimated_amount FROM api_usage_events ORDER BY started_at'))).mappings())
                assert [r['state'] for r in events]==['succeeded','error','unknown','unknown','error']
                assert all(r['estimated_amount'] is None for r in events)
                assert await session.scalar(select(func.count()).select_from(SeoBacklink))==0
    asyncio.run(run())
