"""Native review HTTP responses after real commits, including ORM expiry."""
import asyncio
from contextlib import asynccontextmanager
import os

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.seo import review_distribution_variant
from app.database import get_session
from app.models.user import User
from app.models.role import Role
from app.models.seo import SeoDistributionVariant, SeoContentAsset, SeoContentConfirmation
from app.security.auth import issue_token
from test_seo_browser_channel_sources_postgres import browser_fixture
from test_seo_distribution_sources_postgres import load

pytestmark = pytest.mark.skipif(not os.getenv('SEO_WORKFLOW_TEST_DATABASE_URL'),
    reason='isolated local PostgreSQL required')
PATH = '/api/v1/seo/content-distribution/variants/60/review'
FIELDS = {'id', 'tenant_id', 'content_id', 'content_title', 'source_title', 'source_content_html',
    'connection_id', 'connection_name', 'platform_code', 'platform_name', 'source_version',
    'current_source_version', 'revision_number', 'status', 'stored_status', 'stale', 'title',
    'excerpt', 'content', 'content_html', 'content_chars', 'content_rules', 'keyword_checks',
    'warnings', 'ai_generated', 'instruction', 'feedback', 'review_note', 'reviewed_by',
    'reviewed_at', 'created_by', 'created_at', 'updated_at'}


@asynccontextmanager
async def environment(expire_on_commit):
    async with browser_fixture() as sessions:
        async with sessions.begin() as db:
            row = await db.get(SeoDistributionVariant, 60)
            row.status, row.reviewed_by, row.reviewed_at = 'pending_review', None, None
        async with sessions.begin() as db:
            raw = await (await db.connection()).get_raw_connection()
            # Test-only transactional audit proves a single durable review
            # UPDATE. The native variant endpoint has no separate event table.
            await raw.driver_connection.execute('''
                CREATE TABLE review_response_audit (variant_id bigint, status text, reviewer bigint);
                CREATE FUNCTION review_response_audit_fn() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                  INSERT INTO review_response_audit VALUES (NEW.id, NEW.status, NEW.reviewed_by);
                  RETURN NEW;
                END; $$;
                CREATE TRIGGER review_response_audit_trigger AFTER UPDATE ON seo_distribution_variants
                FOR EACH ROW WHEN (OLD.reviewed_at IS DISTINCT FROM NEW.reviewed_at)
                EXECUTE FUNCTION review_response_audit_fn();
            ''')
        # Test the production setting False AND stronger whole-identity expiry.
        # No mock commit/flush/refresh or disabling ORM server-default expiry.
        request_sessions = async_sessionmaker(sessions.kw['bind'], expire_on_commit=expire_on_commit)
        app = FastAPI()
        async def db_dep():
            async with request_sessions() as db: yield db
        app.dependency_overrides[get_session] = db_dep
        app.add_api_route('/api/v1/seo/content-distribution/variants/{variant_id}/review',
            review_distribution_variant, methods=['POST'])
        async with sessions() as db: token = issue_token(await db.get(User, 7))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                     base_url='http://synthetic') as client:
            yield sessions, client, {'Authorization': 'Bearer ' + token}


@pytest.mark.parametrize('expire_on_commit', [False, True])
@pytest.mark.parametrize('decision,status', [('approve', 'approved'), ('reject', 'rejected')])
def test_commit_then_full_serializable_response_and_single_review(expire_on_commit, decision, status):
    async def scenario():
        async with environment(expire_on_commit) as (sessions, client, headers):
            payload = {'tenant_id': 4, 'site_id': 2, 'decision': decision, 'note': 'synthetic review'}
            response = await client.post(PATH, headers=headers, json=payload)
            # Read through a different committed transaction before asserting
            # HTTP success: the original bug committed successfully then 500ed.
            async with sessions() as db:
                row = await db.get(SeoDistributionVariant, 60)
                assert row.status == status and row.reviewed_by == 7 and row.reviewed_at is not None
                assert await db.scalar(text('SELECT count(*) FROM review_response_audit')) == 1
                if decision == 'approve':
                    snapshot = await load(db)
                    assert snapshot['variant_id'] == 60
                else:
                    with pytest.raises(HTTPException) as exc: await load(db)
                    assert exc.value.detail['code'] == 'seo_distribution_review_required'
                assert response.status_code == 200, response.text
                result = response.json()
                assert set(result) == FIELDS
                assert result['status'] == result['stored_status'] == status
                assert result['reviewed_by'] == 7 and result['review_note'] == 'synthetic review'
                assert result['reviewed_at'] and result['updated_at'] and result['created_at']
                assert result['platform_code'] == 'wechat_browser'
                assert result['id'] == 60 and result['connection_id'] == 50 and result['content_id'] == 40
                assert result['source_version'] == result['current_source_version'] == 3
                assert result['content'] == result['content_html'] == row.content
                assert result['stale'] is False
                stored_review_time = row.reviewed_at
            repeated = await client.post(PATH, headers=headers, json=payload)
            assert repeated.status_code == 409
            async with sessions() as db:
                assert await db.scalar(text('SELECT count(*) FROM review_response_audit')) == 1
                row = await db.get(SeoDistributionVariant, 60)
                assert row.reviewed_at == stored_review_time and row.status == status
    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['anonymous', 'role', 'actor', 'tenant', 'site', 'old_master', 'old_variant'])
def test_review_denied_requests_make_no_committed_review(change):
    async def scenario():
        async with environment(False) as (sessions, client, headers):
            payload = {'tenant_id': 4, 'site_id': 2, 'decision': 'approve'}
            async with sessions.begin() as db:
                if change == 'role': (await db.get(Role, 5)).permissions = {'seo.content': 'view'}
                if change == 'actor': (await db.get(User, 7)).is_active = False
                if change == 'tenant': payload['tenant_id'] = 9
                if change == 'site': payload['site_id'] = 9
                if change == 'old_master': (await db.get(SeoContentAsset, 40)).version_count = 4
                if change == 'old_variant': db.add(SeoDistributionVariant(id=61, tenant_id=4, content_asset_id=40,
                    connection_id=50, platform_code='wechat_browser', source_version=3, revision_number=3,
                    status='pending_review', title='selection new', content='<p>selection new</p>'))
            response = await client.post(PATH, headers={} if change == 'anonymous' else headers, json=payload)
            assert response.status_code in {401, 403, 404, 409}, response.text
            if change.startswith('old_'): assert response.status_code == 409
            async with sessions() as db:
                row = await db.get(SeoDistributionVariant, 60)
                assert row.status == 'pending_review' and row.reviewed_by is None and row.reviewed_at is None
                assert await db.scalar(text('SELECT count(*) FROM review_response_audit')) == 0
    asyncio.run(scenario())


def test_approval_response_does_not_replace_customer_confirmation():
    async def scenario():
        async with environment(False) as (sessions, client, headers):
            async with sessions.begin() as db: (await db.get(SeoContentConfirmation, 70)).decision = 'reject'
            response = await client.post(PATH, headers=headers, json={
                'tenant_id': 4, 'site_id': 2, 'decision': 'approve'})
            assert response.status_code == 200, response.text
            async with sessions() as db:
                assert (await db.get(SeoDistributionVariant, 60)).status == 'approved'
                assert await db.scalar(text('SELECT count(*) FROM review_response_audit')) == 1
                with pytest.raises(HTTPException) as exc: await load(db)
                assert exc.value.detail['code'] == 'seo_distribution_confirmation_required'
    asyncio.run(scenario())
