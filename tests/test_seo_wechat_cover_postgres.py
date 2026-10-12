"""Synthetic cover pixels, actual PostgreSQL/native JWT/roles/source/media.

No native authorization, content confirmation or asset writer is mocked. ASGI
HTTP is in-process (not a TLS/browser/platform publication test).
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import hashlib
import os
from pathlib import Path

import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text

from app import seo_distribution_media as media, seo_distribution_sources as source
from app.api.seo_distribution_media import router
from app.database import get_session
from app.models.user import User
from app.models.seo import (SeoDistributionVariant, SeoDistributionConnection, SeoContentAsset,
                            SeoContentConfirmation, SeoSiteAdvisorAssignment)
from app.security.auth import issue_token, require_auth
from test_seo_distribution_media_postgres import images_fixture, picture
from test_seo_distribution_sources_postgres import fixture

pytestmark = pytest.mark.skipif(not os.getenv('SEO_WORKFLOW_TEST_DATABASE_URL'), reason='owned local PostgreSQL required')


@asynccontextmanager
async def covers(platform='wechat_browser'):
    async with images_fixture() as sessions:
        async with sessions.begin() as db:
            variant = await db.get(SeoDistributionVariant, 60)
            variant.platform_code = platform
            account = await db.get(SeoDistributionConnection, 50)
            account.platform_code = platform
            account.mode = 'assisted' if platform == 'wechat_browser' else 'manual'
            account.status = 'ready' if platform == 'wechat_browser' else 'manual_required'
        yield sessions


async def upload_cover(db, raw=None):
    draft = await media.preview(db, 7, 4, 2, 60)
    return await media.replace_assets(db, 7, 4, 2, 60, draft['edit_token'], [raw or picture()])


async def freeze_cover(sessions, raw=None):
    async with sessions.begin() as db: draft = await upload_cover(db, raw)
    async with sessions.begin() as db:
        snapshot = await media.review_assets(db, 8, 4, 2, 60, draft['edit_token'], draft['set_id'])
    return draft, snapshot


@pytest.mark.parametrize('platform,fmt', [('wechat_browser','PNG'), ('wechat_official','JPEG')])
def test_native_single_cover_review_source_and_readonly_bytes_without_body_change(platform, fmt, monkeypatch):
    async def forbidden(*args, **kwargs): pytest.fail('External network forbidden')
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', forbidden)
    async def run():
        async with covers(platform) as sessions:
            async with sessions() as db:
                old = await source.load_source(db, 7, 4, 2, 60, 'wechat-article')
                before = await db.get(SeoContentAsset, 40)
                mother = (before.version_count, before.draft, before.title)
                with pytest.raises(HTTPException) as exc:
                    await source.load_publication_source(db, 7, 4, 2, 60, 'wechat-article')
                assert exc.value.detail['code'] == 'seo_distribution_cover_required'
            draft, approved = await freeze_cover(sessions, picture(fmt))
            assert draft['asset_role'] == 'cover' and draft['max_images'] == 1
            assert draft['platform'] == 'wechat-article' and draft['status'] == 'draft'
            assert approved['content']['body'] == old['content']['body']
            assert '<img' not in approved['content']['body'] and len(approved['content']['assets']) == 1
            assert approved['source_revision'] != old['source_revision']
            async with sessions() as db:
                await db.execute(text('SET TRANSACTION READ ONLY'))
                assert await source.load_publication_source(db, 7, 4, 2, 60, 'wechat-article') == approved
                asset = approved['content']['assets'][0]
                data = await source.load_asset(db, 7, 4, 2, 60, 'wechat-article', asset['id'])
                assert len(data) == asset['bytes'] and hashlib.sha256(data).hexdigest() == asset['sha256']
                after = await db.get(SeoContentAsset, 40)
                assert (after.version_count, after.draft, after.title) == mother
                assert not db.new and not db.dirty
    asyncio.run(run())


def test_one_cover_limit_and_upload_cannot_self_review_or_borrow_an_alias():
    async def run():
        async with covers() as sessions:
            async with sessions() as db:
                before = await media.preview(db, 7, 4, 2, 60)
                for images in ([], [picture(), picture('JPEG')]):
                    with pytest.raises(HTTPException) as exc:
                        await media.replace_assets(db, 7, 4, 2, 60, before['edit_token'], images)
                    assert exc.value.status_code == 422
                assert await media.preview(db, 7, 4, 2, 60) == before
            async with sessions.begin() as db: draft = await upload_cover(db)
            with pytest.raises(HTTPException) as exc:
                async with sessions.begin() as db:
                    await media.review_assets(db, 7, 4, 2, 60, draft['edit_token'], draft['set_id'])
            assert exc.value.status_code == 403
            async with sessions.begin() as db:
                (await db.get(SeoDistributionConnection, 50)).platform_code = 'wechat_official'
            async with sessions() as db:
                with pytest.raises(HTTPException): await media.preview(db, 7, 4, 2, 60)
                with pytest.raises(HTTPException): await source.load_source(db, 7, 4, 2, 60, 'wechat-article')
    asyncio.run(run())


def test_cover_intake_version_changes_on_upload_stable_through_approval_and_replacement():
    async def run():
        async with covers() as sessions:
            async with sessions() as db:
                original = (await source.list_intake_candidates(db, 7, 4, 2, 'wechat-article'))['items'][0]
            async with sessions.begin() as db: first = await upload_cover(db)
            async with sessions() as db:
                pending = await source.load_intake_candidate(db, 7, 4, 2, 60, 'wechat-article')
                assert pending['readiness'] == 'awaiting-review' and pending['source_revision'] is None
                assert pending['draft_version'] != original['draft_version']
                assert 'selection' not in str(pending) and 'sha256' not in str(pending)
            async with sessions.begin() as db:
                sealed = await media.review_assets(db, 8, 4, 2, 60, first['edit_token'], first['set_id'])
            async with sessions() as db:
                ready = await source.load_intake_candidate(db, 7, 4, 2, 60, 'wechat-article')
                assert ready['draft_version'] == pending['draft_version']
                assert ready['readiness'] == 'ready' and ready['source_revision'] == sealed['source_revision']
            replacement, latest = await freeze_cover(sessions, picture('JPEG', 'green'))
            assert latest['source_revision'] != sealed['source_revision']
            async with sessions() as db:
                current = await source.load_intake_candidate(db, 7, 4, 2, 60, 'wechat-article')
                assert current['draft_version'] != ready['draft_version']
                with pytest.raises(HTTPException) as exc:
                    await source.load_asset(db, 7, 4, 2, 60, 'wechat-article', first['assets'][0]['id'])
                assert exc.value.status_code == 404
    asyncio.run(run())


@pytest.mark.parametrize('change', ['body', 'mother', 'confirmation', 'legacy_review', 'assignment', 'creator_review', 'scope', 'bytes'])
def test_cover_current_review_scope_confirmation_and_bytes_are_required(change):
    async def run():
        async with covers() as sessions:
            draft, snapshot = await freeze_cover(sessions)
            async with sessions.begin() as db:
                if change == 'body': (await db.get(SeoDistributionVariant, 60)).content = '<p>selection changed</p>'
                elif change == 'mother': (await db.get(SeoContentAsset, 40)).version_count += 1
                elif change == 'confirmation': (await db.get(SeoContentConfirmation, 70)).decision = 'reject'
                elif change == 'legacy_review':
                    row = await db.get(SeoDistributionVariant, 60); row.reviewed_at = datetime(2026,10,12)
                elif change == 'assignment': (await db.get(SeoSiteAdvisorAssignment, 3)).active = False
                elif change == 'creator_review': (await db.get(SeoDistributionVariant, 60)).created_by = 8
                elif change == 'scope': (await db.get(SeoContentAsset, 40)).site_id = 999
                else:
                    await db.execute(text('ALTER TABLE seo_distribution_media_bytes DISABLE TRIGGER seo_media_bytes_immutable'))
                    await db.execute(text('UPDATE seo_distribution_media_bytes SET data=set_byte(data,0,0)'))
                    await db.execute(text('ALTER TABLE seo_distribution_media_bytes ENABLE TRIGGER seo_media_bytes_immutable'))
            async with sessions() as db:
                with pytest.raises(HTTPException):
                    await source.load_asset(db, 7, 4, 2, 60, 'wechat-article', snapshot['content']['assets'][0]['id'])
                if change != 'bytes':
                    with pytest.raises(HTTPException): await source.load_publication_source(db, 7, 4, 2, 60, 'wechat-article')
    asyncio.run(run())


def test_optional_tables_do_not_change_plaintext_fingerprint_and_partial_schema_fails_closed():
    async def run():
        async with fixture() as sessions:
            async with sessions() as db:
                original = await source.load_source(db, 7, 4, 2, 60, 'wechat-article')
                intake = await source.load_intake_candidate(db, 7, 4, 2, 60, 'wechat-article')
            async with sessions.begin() as db:
                raw = (await (await db.connection()).get_raw_connection()).driver_connection
                await raw.execute((Path(__file__).parents[1]/'scripts/seo_distribution_media_schema.sql').read_text())
            async with sessions() as db:
                assert await source.load_source(db, 7, 4, 2, 60, 'wechat-article') == original
                assert await source.load_intake_candidate(db, 7, 4, 2, 60, 'wechat-article') == intake
            async with sessions.begin() as db:
                await db.execute(text('ALTER TABLE seo_distribution_media_reviews RENAME TO seo_missing_reviews'))
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc:
                    await source.load_source(db, 7, 4, 2, 60, 'wechat-article')
                assert exc.value.status_code == 503
    asyncio.run(run())


def test_native_jwt_cover_http_upload_independent_review_and_current_revoke():
    async def run():
        async with covers() as sessions:
            app = FastAPI(); app.include_router(router)
            async def database():
                async with sessions() as db: yield db
            app.dependency_overrides[get_session] = database
            @app.get('/native-publication-source')
            async def publication(ctx=Depends(require_auth), db=Depends(get_session)):
                return await source.load_publication_source(db, ctx.user_id, 4, 2, 60, 'wechat-article')
            async with sessions() as db:
                author = {'Authorization':'Bearer '+issue_token(await db.get(User, 7))}
                reviewer = {'Authorization':'Bearer '+issue_token(await db.get(User, 8))}
            path = '/api/seo/distribution-media/variants/60'; scope = {'tenant_id':4, 'site_id':2}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://synthetic') as client:
                assert (await client.get('/native-publication-source')).status_code == 401
                preview = (await client.get(path, params=scope, headers=author)).json()
                bad = await client.post(path+'/assets', headers=author, data={**scope, 'expected_token':preview['edit_token']},
                    files=[('files',('one.png',picture(),'image/png')), ('files',('two.jpg',picture('JPEG'),'image/jpeg'))])
                assert bad.status_code == 422
                draft = (await client.post(path+'/assets', headers=author, data={**scope, 'expected_token':preview['edit_token']},
                    files=[('files',('ignored.png',picture(),'image/png'))])).json()
                review = {**scope, 'expected_token':draft['edit_token'], 'set_id':draft['set_id']}
                assert (await client.post(path+'/review', headers=author, json=review)).status_code == 403
                approved = await client.post(path+'/review', headers=reviewer, json=review)
                assert approved.status_code == 200 and len(approved.json()['content']['assets']) == 1
                assert (await client.get('/native-publication-source', headers=author)).status_code == 200
                async with sessions.begin() as db: (await db.get(SeoSiteAdvisorAssignment, 3)).active = False
                assert (await client.get('/native-publication-source', headers=author)).status_code == 403
                assert (await client.get(path, params={**scope,'tenant_id':9}, headers=reviewer)).status_code == 403
    asyncio.run(run())
