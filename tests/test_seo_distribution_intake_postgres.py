"""Real local PG/JWT intake contract; no production or platform requests."""
import asyncio
from datetime import datetime
import os
import re

import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app import seo_distribution_sources as source
from app.database import get_session
from app.models.user import User
from app.models.role import Role
from app.models.module_workspace import SeoSite, TenantModule
from app.models.seo import (SeoDistributionVariant, SeoContentAsset, SeoContentConfirmation,
    SeoDistributionConnection, SeoSiteAdvisorAssignment)
from app.security.auth import issue_token, require_auth
from test_seo_distribution_sources_postgres import fixture, load, listing
from test_seo_distribution_media_postgres import images_fixture, upload, picture
from app import seo_distribution_media as media

pytestmark = pytest.mark.skipif(not os.getenv('SEO_WORKFLOW_TEST_DATABASE_URL'),
    reason='isolated local PostgreSQL required')


async def intake(db, **overrides):
    return await source.list_intake_candidates(db, **dict(
        actor_user_id=7, tenant_id=4, scope_id=2, platform='wechat-article', **overrides))


def check(page):
    assert set(page) == {'items', 'next_cursor'}
    for item in page['items']:
        assert set(item) == {'variant_id', 'draft_version', 'source_revision', 'readiness', 'reason'}
        assert type(item['variant_id']) is int and item['variant_id'] > 0
        assert re.fullmatch(r'[A-Za-z0-9_-]{1,100}', item['draft_version'])
        assert re.fullmatch(r'[A-Za-z0-9_]{1,64}', item['reason'])
        if item['readiness'] == 'ready':
            assert re.fullmatch(r'[A-Za-z0-9_-]{1,100}', item['source_revision'])
        else:
            assert item['readiness'] in {'awaiting-review', 'awaiting-adaptation'}
            assert item['source_revision'] is None
    assert page['next_cursor'] is None or type(page['next_cursor']) is int and page['next_cursor'] > 0


def test_readonly_metadata_and_no_identity_map_flush_commit_or_network(monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail('Readonly intake attempted a write or external transport')
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', forbidden)
    async def scenario():
        async with fixture() as sessions:
            async with sessions() as db:
                await db.execute(text('SET TRANSACTION READ ONLY'))
                row = await db.get(SeoDistributionVariant, 60)
                pending = SeoDistributionVariant(id=61, tenant_id=4, content_asset_id=40, connection_id=50,
                    platform_code='wechat_official', source_version=3, revision_number=3,
                    status='draft', title='uncommitted secret', content='uncommitted secret')
                expected = await load(db)
                row.content = 'uncommitted secret'
                db.add(pending)
                monkeypatch.setattr(db, 'commit', forbidden)
                monkeypatch.setattr(db, 'flush', forbidden)
                page = await intake(db)
                check(page)
                assert len(page['items']) == 1 and page['next_cursor'] is None
                assert page['items'][0]['source_revision'] == expected['source_revision']
                assert row in db.dirty and pending in db.new and db.in_transaction()
                assert 'selection' not in str(page) and 'secret' not in str(page)
    asyncio.run(scenario())


def test_review_changes_reuse_version_and_content_edits_change_it():
    async def scenario():
        async with fixture() as sessions:
            async with sessions() as db:
                first = (await intake(db))['items'][0]
            for status in ('draft', 'pending_review', 'rejected', 'approved'):
                async with sessions.begin() as db:
                    row = await db.get(SeoDistributionVariant, 60)
                    row.status = status
                    row.reviewed_at = datetime(2026, 10, 12)
                    row.review_note = 'review metadata must not become a draft version'
                async with sessions() as db:
                    page = await intake(db)
                    check(page)
                    item = page['items'][0]
                    assert item['draft_version'] == first['draft_version']
                    if status == 'approved':
                        assert item['source_revision'] == (await load(db))['source_revision']
                        assert len(await listing(db)) == 1
                    else:
                        assert item['reason'] == 'review_required'
                        assert item['source_revision'] is None and await listing(db) == []
                        with pytest.raises(HTTPException) as exc: await load(db)
                        assert exc.value.detail['code'] == 'seo_distribution_review_required'
            async with sessions.begin() as db:
                (await db.get(SeoDistributionVariant, 60)).content = '<p>selection edited</p>'
            async with sessions() as db:
                assert (await intake(db))['items'][0]['draft_version'] != first['draft_version']
    asyncio.run(scenario())


def test_media_replacement_changes_version_independent_review_does_not():
    async def scenario():
        async with images_fixture() as sessions:
            async with sessions.begin() as db: uploaded = await upload(db)
            async with sessions() as db:
                pending = (await source.list_intake_candidates(db, 7, 4, 2, 'xiaohongshu-image'))['items'][0]
                assert pending['readiness'] == 'awaiting-review'
                assert pending['source_revision'] is None
            async with sessions.begin() as db:
                await media.review_assets(db, 8, 4, 2, 60, uploaded['edit_token'], uploaded['set_id'])
            async with sessions() as db:
                page = await source.list_intake_candidates(db, 7, 4, 2, 'xiaohongshu-image')
                check(page)
                approved = page['items'][0]
                assert approved['draft_version'] == pending['draft_version']
                assert approved['source_revision'] == (await source.load_source(db, 7, 4, 2, 60,
                    'xiaohongshu-image'))['source_revision']
            async with sessions.begin() as db: await upload(db, [picture('PNG', 'green')])
            async with sessions() as db:
                replaced = (await source.list_intake_candidates(db, 7, 4, 2, 'xiaohongshu-image'))['items'][0]
                assert replaced['draft_version'] != approved['draft_version']
                assert replaced['source_revision'] is None
    asyncio.run(scenario())


@pytest.mark.parametrize('status,expected', [('generating', []), ('queued', []), ('failed', []),
    ('draft', [61]), ('pending_review', [61]), ('rejected', [61]), ('approved', [61]), ('published', [61])])
def test_latest_revision_selected_before_finished_status_filter(status, expected):
    async def scenario():
        async with fixture() as sessions:
            async with sessions.begin() as db:
                db.add(SeoDistributionVariant(id=61, tenant_id=4, content_asset_id=40, connection_id=50,
                    platform_code='wechat_official', source_version=3, revision_number=3,
                    status=status, title='selection latest', content='<p>selection latest</p>'))
            async with sessions() as db:
                page = await intake(db)
                check(page)
                assert [item['variant_id'] for item in page['items']] == expected
                with pytest.raises(HTTPException) as exc: await load(db)
                assert exc.value.detail['code'] == 'seo_distribution_source_stale'
    asyncio.run(scenario())


def test_pagination_over_fifty_tail_and_restart_for_approval():
    async def scenario():
        async with fixture() as sessions:
            async with sessions.begin() as db:
                for n in range(1, 55):
                    db.add(SeoDistributionConnection(id=50+n, tenant_id=4, platform_code='wechat_official',
                        name=f'synthetic-{n}', mode='manual', enabled=True, status='manual_required'))
                    db.add(SeoDistributionVariant(id=60+n, tenant_id=4, content_asset_id=40, connection_id=50+n,
                        platform_code='wechat_official', source_version=3, revision_number=1,
                        status='pending_review', title='selection pending', content='<p>selection pending</p>'))
            async with sessions() as db:
                first = await intake(db)
                assert len(first['items']) == 50 and first['next_cursor'] == 109
                tail = await intake(db, after_variant_id=first['next_cursor'])
                assert [x['variant_id'] for x in tail['items']] == list(range(110, 115))
                assert tail['next_cursor'] is None
                assert (await intake(db, after_variant_id=114)) == {'items': [], 'next_cursor': None}
                exact = await intake(db, after_variant_id=109, limit=5)
                assert exact == tail
                single = await intake(db, limit=1)
                assert single['next_cursor'] == 60
                for page in (first, tail, single): check(page)
            async with sessions.begin() as db:
                row = await db.get(SeoDistributionVariant, 61)
                row.status, row.reviewed_by, row.reviewed_at = 'approved', 7, datetime(2026, 10, 12)
            async with sessions() as db:
                rescanned = (await intake(db))['items'][1]
                assert rescanned['readiness'] == 'ready'
                assert rescanned['draft_version'] == first['items'][1]['draft_version']
    asyncio.run(scenario())


@pytest.mark.parametrize('kwargs', [{'limit': 0}, {'limit': 51}, {'limit': True}, {'limit': 1.0},
    {'limit': '2'}, {'after_variant_id': 0}, {'after_variant_id': -1}, {'after_variant_id': True},
    {'after_variant_id': 1.0}, {'after_variant_id': '60'}, {'after_variant_id': 2**63}])
def test_invalid_paging_rejected(kwargs):
    async def scenario():
        async with fixture() as sessions:
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc: await intake(db, **kwargs)
                assert exc.value.status_code == 422
    asyncio.run(scenario())


@pytest.mark.parametrize('change,code', [('connection', 'connection_unavailable'),
    ('api', 'connection_unavailable'), ('stale', 'source_stale'), ('confirmation', 'confirmation_required'),
    ('body', 'content_invalid'), ('keywords', 'keywords_invalid'), ('image', 'assets_unavailable')])
def test_known_business_waits_only(change, code):
    async def scenario():
        async with fixture() as sessions:
            async with sessions.begin() as db:
                if change == 'connection': (await db.get(SeoDistributionConnection, 50)).enabled = False
                if change == 'api':
                    account = await db.get(SeoDistributionConnection, 50)
                    account.mode, account.status = 'api', 'unconfigured'
                if change == 'stale': (await db.get(SeoContentAsset, 40)).version_count = 4
                if change == 'confirmation': (await db.get(SeoContentConfirmation, 70)).decision = 'reject'
                if change == 'body': (await db.get(SeoDistributionVariant, 60)).content = ''
                if change == 'keywords': (await db.get(SeoDistributionVariant, 60)).content = '<p>unrelated</p>'
                if change == 'image': (await db.get(SeoDistributionVariant, 60)).content += '<img src="https://example.com/a.png">'
            async with sessions() as db:
                page = await intake(db)
                check(page)
                item = page['items'][0]
                assert item['reason'] == code and item['source_revision'] is None
                assert item['readiness'] == ('awaiting-review' if change == 'confirmation' else 'awaiting-adaptation')
                assert await listing(db) == []
                with pytest.raises(HTTPException): await load(db)
    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['user', 'role', 'assignment', 'tenant', 'site', 'module'])
def test_current_scope_revocation_never_maps_to_waiting(change):
    async def scenario():
        async with fixture() as sessions:
            async with sessions() as cached:
                await cached.get(User, 7)
                assert len((await intake(cached))['items']) == 1
                async with sessions.begin() as db:
                    if change == 'user': (await db.get(User, 7)).is_active = False
                    if change == 'role': (await db.get(Role, 5)).permissions = {}
                    if change == 'assignment': (await db.get(SeoSiteAdvisorAssignment, 3)).active = False
                    if change == 'tenant': (await db.get(User, 7)).tenant_id = 9
                    if change == 'site': (await db.get(SeoSite, 2)).tenant_id = 9
                    if change == 'module': (await db.get(TenantModule, 1)).status = 'paused'
                with pytest.raises(HTTPException) as exc: await intake(cached)
                assert exc.value.status_code in (403, 404, 409)
    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['content_scope', 'content_tenant', 'account_tenant', 'variant_tenant', 'qa'])
def test_cross_scope_sources_excluded(change):
    async def scenario():
        async with fixture() as sessions:
            async with sessions.begin() as db:
                if change == 'content_scope': (await db.get(SeoContentAsset, 40)).site_id = 9
                if change == 'content_tenant': (await db.get(SeoContentAsset, 40)).tenant_id = 9
                if change == 'account_tenant': (await db.get(SeoDistributionConnection, 50)).tenant_id = 9
                if change == 'variant_tenant': (await db.get(SeoDistributionVariant, 60)).tenant_id = 9
                if change == 'qa': (await db.get(SeoContentAsset, 40)).content_type = 'qa'
            async with sessions() as db: assert await intake(db) == {'items': [], 'next_cursor': None}
    asyncio.run(scenario())


@pytest.mark.parametrize('table', ['seo_content_confirmations', 'seo_distribution_variants'])
def test_database_failure_is_503_not_adaptation(table):
    async def scenario():
        async with fixture() as sessions:
            async with sessions.begin() as db: await db.execute(text('DROP TABLE ' + table))
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc: await intake(db)
                assert exc.value.status_code == 503
                assert exc.value.detail['code'] == 'seo_distribution_source_unavailable'
    asyncio.run(scenario())


def test_missing_media_structure_fails_even_for_pending_draft():
    async def scenario():
        async with fixture() as sessions:
            async with sessions.begin() as db:
                row = await db.get(SeoDistributionVariant, 60)
                row.platform_code, row.status = 'xiaohongshu', 'pending_review'
                (await db.get(SeoDistributionConnection, 50)).platform_code = 'xiaohongshu'
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc:
                    await source.list_intake_candidates(db, 7, 4, 2, 'xiaohongshu-image')
                assert exc.value.status_code == 503
    asyncio.run(scenario())


def test_actual_jwt_and_scope_rechecked():
    async def scenario():
        async with fixture() as sessions:
            app = FastAPI()
            async def db_dep():
                async with sessions() as db: yield db
            app.dependency_overrides[get_session] = db_dep
            @app.get('/synthetic-intake')
            async def endpoint(tenant_id: int = 4, site_id: int = 2,
                               ctx=Depends(require_auth), db=Depends(get_session)):
                return await source.list_intake_candidates(db, ctx.user_id, tenant_id, site_id, 'wechat-article')
            async with sessions() as db: token = issue_token(await db.get(User, 7))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://synthetic') as client:
                assert (await client.get('/synthetic-intake')).status_code == 401
                headers = {'Authorization': 'Bearer ' + token}
                response = await client.get('/synthetic-intake', headers=headers)
                assert response.status_code == 200
                check(response.json())
                assert (await client.get('/synthetic-intake?tenant_id=9', headers=headers)).status_code in (403, 404)
                assert (await client.get('/synthetic-intake?site_id=9', headers=headers)).status_code in (403, 404)
                async with sessions.begin() as db: (await db.get(Role, 5)).permissions = {}
                assert (await client.get('/synthetic-intake', headers=headers)).status_code == 403
    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['body', 'latest', 'revoke'])
def test_concurrent_change_cannot_pair_old_version_with_new_seal(monkeypatch, change):
    original = source.load_source
    async def scenario():
        async with fixture() as sessions:
            async def mutate_then_load(*args, **kwargs):
                async with sessions.begin() as db:
                    if change == 'body': (await db.get(SeoDistributionVariant, 60)).content = '<p>selection changed</p>'
                    if change == 'revoke': (await db.get(Role, 5)).permissions = {}
                    if change == 'latest': db.add(SeoDistributionVariant(id=61, tenant_id=4, content_asset_id=40,
                        connection_id=50, platform_code='wechat_official', source_version=3,
                        revision_number=3, status='draft', title='selection latest', content='<p>selection latest</p>'))
                return await original(*args, **kwargs)
            monkeypatch.setattr(source, 'load_source', mutate_then_load)
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc: await intake(db)
                assert exc.value.status_code == (403 if change == 'revoke' else 409)
                if change != 'revoke': assert exc.value.detail['code'] == 'seo_distribution_source_changed'
    asyncio.run(scenario())


def test_empty_page_final_authorization(monkeypatch):
    original = source.authorize_scope
    async def scenario():
        async with fixture() as sessions:
            calls = 0
            async def authorize(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    async with sessions.begin() as db: (await db.get(Role, 5)).permissions = {}
                return await original(*args, **kwargs)
            monkeypatch.setattr(source, 'authorize_scope', authorize)
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc: await intake(db, after_variant_id=999)
                assert exc.value.status_code == 403 and calls == 2
    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['absent', 'generating', 'replaced', 'scope', 'platform'])
def test_point_candidate_none_only_for_noncurrent_or_nonmatching_id(change):
    async def scenario():
        async with fixture() as sessions:
            async with sessions.begin() as db:
                row = await db.get(SeoDistributionVariant, 60)
                row.status = 'pending_review'
                if change == 'absent': await db.delete(row)
                if change == 'generating': row.status = 'generating'
                if change == 'scope': (await db.get(SeoContentAsset, 40)).site_id = 9
                if change == 'platform':
                    row.platform_code = 'xiaohongshu'
                    (await db.get(SeoDistributionConnection, 50)).platform_code = 'xiaohongshu'
                if change == 'replaced': db.add(SeoDistributionVariant(id=61, tenant_id=4, content_asset_id=40,
                    connection_id=50, platform_code='wechat_official', source_version=3, revision_number=3,
                    status='draft', title='selection replacement', content='<p>selection replacement</p>'))
            async with sessions() as db:
                assert await source.load_intake_candidate(db, 7, 4, 2, 60, 'wechat-article') is None
                if change == 'replaced':
                    newer = await source.load_intake_candidate(db, 7, 4, 2, 61, 'wechat-article')
                    assert newer['readiness'] == 'awaiting-review'
    asyncio.run(scenario())


def test_point_reuses_version_and_same_connection_without_flush(monkeypatch):
    async def forbidden(*args, **kwargs): pytest.fail('Point intake attempted write or new connection')
    async def scenario():
        async with fixture() as sessions:
            async with sessions.begin() as db: (await db.get(SeoDistributionVariant, 60)).status = 'pending_review'
            async with sessions() as db:
                await db.execute(text('SET TRANSACTION READ ONLY'))
                row = await db.get(SeoDistributionVariant, 60)
                row.content = 'uncommitted private body'
                monkeypatch.setattr(db, 'flush', forbidden)
                monkeypatch.setattr(db, 'commit', forbidden)
                # All scalar queries must reuse this transaction's connection.
                def forbidden_connection(*args, **kwargs): pytest.fail('Extra database connection opened')
                monkeypatch.setattr(sessions.kw['bind'].sync_engine, 'connect', forbidden_connection)
                pending = await source.load_intake_candidate(db, 7, 4, 2, 60, 'wechat-article')
                assert pending == (await intake(db))['items'][0]
                assert pending['source_revision'] is None
            monkeypatch.undo()
            async with sessions.begin() as db: (await db.get(SeoDistributionVariant, 60)).status = 'approved'
            async with sessions() as db:
                approved = await source.load_intake_candidate(db, 7, 4, 2, 60, 'wechat-article')
                assert approved['draft_version'] == pending['draft_version']
                assert approved['source_revision'] == (await load(db))['source_revision']
                assert approved == (await intake(db))['items'][0]
    asyncio.run(scenario())


@pytest.mark.parametrize('change,status', [('revoke', 403), ('schema', 503)])
def test_point_errors_never_become_none(change, status):
    async def scenario():
        async with fixture() as sessions:
            async with sessions.begin() as db:
                if change == 'revoke': (await db.get(Role, 5)).permissions = {}
                else: await db.execute(text('DROP TABLE seo_content_confirmations'))
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc:
                    await source.load_intake_candidate(db, 7, 4, 2, 60, 'wechat-article')
                assert exc.value.status_code == status
    asyncio.run(scenario())


@pytest.mark.parametrize('variant_id', [0, -1, True, '60', 60.0, 2**63])
def test_point_invalid_id(variant_id):
    async def scenario():
        async with fixture() as sessions:
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc:
                    await source.load_intake_candidate(db, 7, 4, 2, variant_id, 'wechat-article')
                assert exc.value.status_code == 422
    asyncio.run(scenario())


def test_single_connection_pool_with_existing_tenant_lock():
    async def scenario():
        async with fixture() as sessions:
            async with sessions() as db: schema = await db.scalar(text('SELECT current_schema()'))
            engine = create_async_engine(sessions.kw['bind'].url, pool_size=1, max_overflow=0,
                pool_timeout=1, connect_args={'server_settings': {'search_path': schema, 'lock_timeout': '1000'}})
            try:
                single = async_sessionmaker(engine, expire_on_commit=False)
                async with single() as db:
                    await db.execute(text('SELECT id FROM tenants WHERE id=4 FOR UPDATE'))
                    pending = await asyncio.wait_for(
                        source.load_intake_candidate(db, 7, 4, 2, 60, 'wechat-article'), timeout=5)
                    page = await asyncio.wait_for(intake(db), timeout=5)
                    assert pending == page['items'][0] and db.in_transaction()
            finally:
                await engine.dispose()
    asyncio.run(scenario())
