"""Browser-mode WeChat source mapping with real local PostgreSQL/JWT.

No browser login, external platform, API key, or actual publication is used.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import os

import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text

from app import seo_distribution_sources as source, seo_distribution as distribution
from app.api.seo import create_distribution_connection
from app.database import get_session
from app.models.user import User
from app.models.role import Role
from app.models.module_workspace import SeoSite, TenantModule
from app.models.seo import (SeoContentAsset, SeoContentConfirmation, SeoDistributionConnection,
    SeoDistributionVariant, SeoSiteAdvisorAssignment)
from app.security.auth import issue_token, require_auth
from test_seo_distribution_sources_postgres import fixture, load, listing
from test_seo_distribution_intake_postgres import intake, check

pytestmark = pytest.mark.skipif(not os.getenv('SEO_WORKFLOW_TEST_DATABASE_URL'),
    reason='isolated local PostgreSQL required')


@asynccontextmanager
async def browser_fixture():
    async with fixture() as sessions:
        async with sessions.begin() as db:
            account = await db.get(SeoDistributionConnection, 50)
            account.platform_code, account.mode, account.status = 'wechat_browser', 'assisted', 'ready'
            account.credentials_encrypted, account.has_credentials = None, False
            (await db.get(SeoDistributionVariant, 60)).platform_code = 'wechat_browser'
        yield sessions


async def point(db, variant_id=60):
    return await source.load_intake_candidate(db, 7, 4, 2, variant_id, 'wechat-article')


def test_real_jwt_native_browser_connection_without_credentials_and_official_rejection(monkeypatch):
    async def no_network(*args, **kwargs): pytest.fail('External transport is forbidden')
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', no_network)
    async def scenario():
        async with fixture() as sessions:
            app = FastAPI()
            async def db_dep():
                async with sessions() as db: yield db
            app.dependency_overrides[get_session] = db_dep
            app.add_api_route('/synthetic-connections', create_distribution_connection, methods=['POST'])
            @app.get('/synthetic-source')
            async def get_source(ctx=Depends(require_auth), db=Depends(get_session)):
                return await source.load_source(db, ctx.user_id, 4, 2, 60, 'wechat-article')
            @app.get('/synthetic-intake')
            async def get_intake(ctx=Depends(require_auth), db=Depends(get_session)):
                return await source.list_intake_candidates(db, ctx.user_id, 4, 2, 'wechat-article')
            async with sessions() as db: token = issue_token(await db.get(User, 7))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://synthetic') as client:
                headers = {'Authorization': 'Bearer ' + token}
                assert (await client.get('/synthetic-source')).status_code == 401
                # Exercise the existing native creation endpoint: the API
                # channel still rejects missing credentials before insertion.
                rejected = await client.post('/synthetic-connections', headers=headers, json={
                    'tenant_id': 4, 'platform_code': 'wechat_official', 'name': 'official-no-credentials'})
                assert rejected.status_code == 400, rejected.text
                created = await client.post('/synthetic-connections', headers=headers, json={
                    'tenant_id': 4, 'platform_code': 'wechat_browser', 'name': 'browser-no-credentials'})
                assert created.status_code == 200, created.text
                account_id = created.json()['id']
                assert created.json()['mode'] == 'assisted' and created.json()['has_credentials'] is False
                async with sessions.begin() as db:
                    account = await db.get(SeoDistributionConnection, account_id)
                    assert account.credentials_encrypted is None and not account.has_credentials
                    row = await db.get(SeoDistributionVariant, 60)
                    row.connection_id, row.platform_code = account_id, 'wechat_browser'
                response = await client.get('/synthetic-source', headers=headers)
                assert response.status_code == 200, response.text
                candidate_page = (await client.get('/synthetic-intake', headers=headers)).json()
                check(candidate_page)
                assert candidate_page['items'][0]['source_revision'] == response.json()['source_revision']
                async with sessions() as db:
                    await db.execute(text('SET TRANSACTION READ ONLY'))
                    assert await load(db) == response.json()
                    assert [x['variant_id'] for x in await listing(db)] == [60]
                    assert await point(db) == candidate_page['items'][0]
                async with sessions.begin() as db: (await db.get(SeoSiteAdvisorAssignment, 3)).active = False
                assert (await client.get('/synthetic-source', headers=headers)).status_code == 403
                assert (await client.get('/synthetic-intake', headers=headers)).status_code == 403
    asyncio.run(scenario())


@pytest.mark.parametrize('change,code', [
    ('pending', 'review_required'), ('master_review', 'review_required'),
    ('unconfirmed', 'confirmation_required'), ('old_master', 'source_stale'),
    ('old_variant', 'source_stale'), ('actor', 'identity_required'),
    ('assignment', 'advisor_required'), ('role', 'advisor_required'),
    ('tenant', 'identity_required'), ('site', 'scope_not_found'), ('module', 'site_unavailable'),
    ('disabled', 'connection_unavailable'), ('api_unconnected', 'connection_unavailable'),
])
def test_browser_mapping_preserves_native_gates(change, code):
    async def scenario():
        async with browser_fixture() as sessions:
            async with sessions.begin() as db:
                if change == 'pending': (await db.get(SeoDistributionVariant, 60)).status = 'pending_review'
                if change == 'master_review': (await db.get(SeoContentAsset, 40)).status = 'review'
                if change == 'unconfirmed': (await db.get(SeoContentConfirmation, 70)).decision = 'reject'
                if change == 'old_master': (await db.get(SeoContentAsset, 40)).version_count = 4
                if change == 'old_variant': db.add(SeoDistributionVariant(id=61, tenant_id=4, content_asset_id=40,
                    connection_id=50, platform_code='wechat_browser', source_version=3, revision_number=3,
                    status='pending_review', title='selection latest', content='<p>selection latest</p>'))
                if change == 'actor': (await db.get(User, 7)).is_active = False
                if change == 'assignment': (await db.get(SeoSiteAdvisorAssignment, 3)).active = False
                if change == 'role': (await db.get(Role, 5)).permissions = {}
                if change == 'tenant': (await db.get(User, 7)).tenant_id = 9
                if change == 'site': (await db.get(SeoSite, 2)).tenant_id = 9
                if change == 'module': (await db.get(TenantModule, 1)).status = 'paused'
                if change == 'disabled': (await db.get(SeoDistributionConnection, 50)).enabled = False
                if change == 'api_unconnected':
                    row = await db.get(SeoDistributionConnection, 50)
                    row.mode, row.status = 'api', 'configured'
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc: await load(db)
                assert exc.value.detail['code'] == 'seo_distribution_' + code
                if code in {'identity_required', 'advisor_required', 'scope_not_found', 'site_unavailable'}:
                    for reader in (listing, intake, point):
                        with pytest.raises(HTTPException) as exc: await reader(db)
                        assert exc.value.detail['code'] == 'seo_distribution_' + code
                else:
                    assert await listing(db) == []
                    page = await intake(db)
                    check(page)
                    assert page['items'][0]['source_revision'] is None
                    if change == 'old_variant':
                        assert await point(db) is None and page['items'][0]['variant_id'] == 61
                    else:
                        assert (await point(db))['reason'] == code
    asyncio.run(scenario())


@pytest.mark.parametrize('variant_code,connection_code', [
    ('wechat_browser', 'wechat_official'), ('wechat_official', 'wechat_browser'),
    ('wechat_browser', 'xiaohongshu'), ('xiaohongshu', 'wechat_browser'),
    ('unregistered', 'unregistered'), ('zhihu', 'zhihu'),
])
def test_native_platform_codes_must_match_exactly_and_be_whitelisted(variant_code, connection_code):
    async def scenario():
        async with browser_fixture() as sessions:
            async with sessions.begin() as db:
                (await db.get(SeoDistributionVariant, 60)).platform_code = variant_code
                (await db.get(SeoDistributionConnection, 50)).platform_code = connection_code
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc: await load(db)
                assert exc.value.detail['code'] == 'seo_distribution_platform_mismatch'
                assert await listing(db) == []
                assert await intake(db) == {'items': [], 'next_cursor': None}
                assert await point(db) is None
    asyncio.run(scenario())


def test_both_transports_keep_separate_connections_and_latest_revisions():
    async def scenario():
        async with browser_fixture() as sessions:
            async with sessions.begin() as db:
                # No fake credentials: fixture only exercises the existing
                # source connection-status gate, not a real official API call.
                db.add(SeoDistributionConnection(id=51, tenant_id=4, platform_code='wechat_official',
                    name='official-status-fixture', mode='api', enabled=True, status='connected'))
                db.add(SeoDistributionVariant(id=61, tenant_id=4, content_asset_id=40, connection_id=51,
                    platform_code='wechat_official', source_version=3, revision_number=99,
                    status='approved', title='selection official', content='<p>selection official</p>',
                    reviewed_by=7, reviewed_at=datetime(2026, 10, 10)))
            async with sessions() as db:
                browser, official = await load(db), await load(db, variant_id=61)
                assert browser['source_revision'] != official['source_revision']
                assert browser['content']['title'] == 'selection article'
                assert official['content']['title'] == 'selection official'
                assert {x['variant_id'] for x in await listing(db)} == {60, 61}
                page = await intake(db)
                assert [x['variant_id'] for x in page['items']] == [60, 61]
                assert page['items'][0] == await point(db, 60)
                assert page['items'][1] == await point(db, 61)
                one = await intake(db, limit=1)
                assert one['next_cursor'] == 60
                assert (await intake(db, after_variant_id=60))['items'] == [page['items'][1]]
            async with sessions.begin() as db:
                db.add(SeoDistributionVariant(id=62, tenant_id=4, content_asset_id=40, connection_id=50,
                    platform_code='wechat_browser', source_version=3, revision_number=3,
                    status='generating', title='', content=''))
            async with sessions() as db:
                assert [x['variant_id'] for x in await listing(db)] == [61]
                assert [x['variant_id'] for x in (await intake(db))['items']] == [61]
                assert await point(db, 60) is None and await point(db, 62) is None
                assert (await point(db, 61))['source_revision'] == official['source_revision']
    asyncio.run(scenario())


def test_browser_draft_version_stable_across_approval():
    async def scenario():
        async with browser_fixture() as sessions:
            async with sessions.begin() as db: (await db.get(SeoDistributionVariant, 60)).status = 'pending_review'
            async with sessions() as db: pending = await point(db)
            async with sessions.begin() as db: (await db.get(SeoDistributionVariant, 60)).status = 'approved'
            async with sessions() as db:
                approved = await point(db)
                assert approved['draft_version'] == pending['draft_version']
                assert pending['source_revision'] is None
                assert approved['source_revision'] == (await load(db))['source_revision']
    asyncio.run(scenario())


def test_browser_metadata_database_errors_fail_closed():
    async def scenario():
        async with browser_fixture() as sessions:
            async with sessions.begin() as db: await db.execute(text('DROP TABLE seo_content_confirmations'))
            async with sessions() as db:
                for reader in (load, listing, intake, point):
                    with pytest.raises(HTTPException) as exc: await reader(db)
                    assert exc.value.status_code == 503
                    await db.rollback()
    asyncio.run(scenario())


def test_catalog_credentials_are_transport_specific():
    assert distribution.platform_definition('wechat_browser')['mode'] == 'assisted'
    assert distribution.platform_definition('wechat_official')['mode'] == 'api'
    assert distribution.normalize_credentials('wechat_browser', None) == {}
    with pytest.raises(distribution.SeoDistributionError): distribution.normalize_credentials('wechat_official', None)
