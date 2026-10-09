"""Inventory continuation, real persisted observations and revoked in-flight reads."""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest
from sqlalchemy import select, func, text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from test_seo_service_workflows import store, create, task, advance
from test_seo_analytics_cycles import database, requires_pg
from app import seo_incremental_crawl as crawl, seo_service_workflows as flows
from app.models.module_workspace import SeoSite, TenantModule
from app.models.seo import SeoSitePage, SeoPageSnapshot, SeoCrawlRun, SeoRankSnapshot
from app.models.seo_cockpit import SeoTask
from app.models.user import User
from app.models.role import Role
from app.seo_crawler import FetchResult


def response(url, body='', status=200, error=None):
    return FetchResult(url, url, status, [], 'text/plain', body, len(body), 1, {}, error, error)


def configure(store, monkeypatch, urls=None):
    monkeypatch.setattr(flows, 'get_settings', lambda: SimpleNamespace(seo_manual_crawl_max_urls_per_tenant_per_day=200))
    store.edit_plan(website_incremental_enabled=True, website_max_pages=1)
    with store.engine.begin() as conn:
        for model in (User, Role):
            conn.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
    with Session(store.engine) as db:
        db.add(Role(id=5, name='fixture', permissions={'seo.site': 'edit', 'seo.content': 'edit'}))
        db.add(User(id=7, username='fixture', password_hash='unused', role_id=5, is_active=True))
        db.commit()
    discovery = AsyncMock(return_value={'urls': urls or ['https://example.com/'], 'sitemap_queue': [],
        'warnings': [], 'sitemaps_checked': [], 'queue_truncated': False, 'more_sitemaps_pending': False})
    monkeypatch.setattr(crawl, 'discover', discovery)
    async def collect(url, **kwargs):
        return {'url': url, 'status_code': 200, 'issue_codes': ['h1_missing'], 'raw_html_hash': 'a'*64,
                'title': '首页', 'internal_links': ['https://example.com/new', 'https://foreign.test/private'],
                'discovery_source': 'incremental', 'click_depth': 0}
    store.collector.side_effect = collect
    return discovery


def finish_round(store, ident):
    for _ in range(4):
        asyncio.run(flows.run_service_workflows())
    return task(store, ident)


def test_discovers_homepage_and_internal_links_without_duplicate_remediation(store, monkeypatch):
    configure(store, monkeypatch)
    first = finish_round(store, create(store, 'website')['task']['id'])
    assert first.status == 'done' and first.completion_evidence['source']['meaning'] == 'incremental_diagnosis_only'
    assert first.completion_evidence['source']['remediation_completed'] is False
    with Session(store.engine) as db:
        pages = list(db.scalars(select(SeoSitePage).order_by(SeoSitePage.id)))
        assert {p.url for p in pages} == {'https://example.com/', 'https://example.com/new'}
        assert db.get(SeoTask, first.params['child_task_ids'][0]).status == 'open'
    second = finish_round(store, create(store, 'website')['task']['id'])
    third = finish_round(store, create(store, 'website')['task']['id'])
    assert set(first.params['pages']) != set(second.params['pages'])
    assert set(first.params['pages']) == set(third.params['pages'])
    assert next(iter(third.params['pages'].values()))['change'] == 'unchanged'
    assert third.params['child_task_ids'] == first.params['child_task_ids']
    with Session(store.engine) as db:
        assert db.scalar(select(func.count()).select_from(SeoPageSnapshot)) == 3
        assert db.scalar(select(func.count()).select_from(SeoTask).where(SeoTask.action_type == 'page_remediation')) == 2
    assert store.collector.call_args.kwargs['allowed_hosts'] == frozenset({'example.com', 'www.example.com'})


def test_known_links_do_not_hide_later_links_and_inventory_limit_is_explicit(store, monkeypatch):
    configure(store, monkeypatch)
    monkeypatch.setattr(crawl, 'DISCOVERY_LIMIT', 2)
    monkeypatch.setattr(crawl, 'INVENTORY_LIMIT', 3)
    async def register():
        async with store.session() as session:
            site = await session.get(SeoSite, 2)
            urls = [f'https://example.com/p/{i}' for i in range(3)]
            first = await crawl.register_urls(session, site, urls)
            assert len(first['added_page_ids']) == 2 and first['more_urls_pending']
            second = await crawl.register_urls(session, site, urls)
            assert len(second['added_page_ids']) == 1
            last = await crawl.register_urls(session, site, ['https://example.com/extra'])
            assert last['inventory_limit_reached'] and not last['added_page_ids']
            await session.commit()
    asyncio.run(register())


def test_sitemap_and_internal_links_share_one_round_discovery_budget(store, monkeypatch):
    configure(store, monkeypatch, ['https://example.com/', 'https://example.com/from-sitemap'])
    monkeypatch.setattr(crawl, 'DISCOVERY_LIMIT', 2)
    row = finish_round(store, create(store, 'website')['task']['id'])
    assert row.params['incremental']['new_page_count'] == 2
    assert row.params['incremental']['inventory']['more_urls_pending']
    with Session(store.engine) as db:
        assert db.scalar(select(func.count()).select_from(SeoSitePage)) == 2


def test_changed_page_references_previous_snapshot_and_keeps_history(store, monkeypatch):
    configure(store, monkeypatch)
    finish_round(store, create(store, 'website')['task']['id'])
    finish_round(store, create(store, 'website')['task']['id'])
    async def changed(url, **kwargs):
        return {'url': url, 'status_code': 200, 'issue_codes': [], 'raw_html_hash': 'b'*64, 'title': '新标题'}
    store.collector.side_effect = changed
    row = finish_round(store, create(store, 'website')['task']['id'])
    observed = next(iter(row.params['pages'].values()))
    assert observed['change'] == 'changed' and 'title' in observed['changed_fields']
    assert observed['previous_snapshot_id'] != observed['snapshot_id']


@pytest.mark.parametrize('revoke', ['pause', 'disable', 'revision', 'user', 'role'])
def test_discovery_result_cannot_register_pages_after_scope_or_permissions_change(store, monkeypatch, revoke):
    configure(store, monkeypatch)
    async def discover(*args):
        with Session(store.engine) as db:
            if revoke in {'pause', 'revision'}:
                site = db.get(SeoSite, 2)
                site.site_settings = {**site.site_settings, 'seo_service_plan': {**site.site_settings['seo_service_plan'],
                    **({'status': 'paused'} if revoke == 'pause' else {'revision': 2})}}
            elif revoke == 'disable':
                db.get(TenantModule, 1).status = 'disabled'
            elif revoke == 'user':
                db.get(User, 7).is_active = False
            else:
                db.get(Role, 5).permissions = {'seo.site': 'view', 'seo.content': 'edit'}
            db.commit()
        return {'urls': ['https://example.com/'], 'error': None}
    monkeypatch.setattr(crawl, 'discover', discover)
    ident = create(store, 'website')['task']['id']
    asyncio.run(flows.execute_discovery(ident))
    with Session(store.engine) as db:
        assert db.scalar(select(func.count()).select_from(SeoSitePage)) == 0
    assert task(store, ident).params['incremental']['state'] == 'failed'
    store.collector.assert_not_awaited()


def test_page_read_discards_result_when_plan_pauses_in_flight(store, monkeypatch):
    configure(store, monkeypatch)
    ident = create(store, 'website')['task']['id']
    asyncio.run(flows.execute_discovery(ident))
    async def paused(url, **kwargs):
        store.edit_plan(status='paused')
        return {'url': url, 'status_code': 200, 'issue_codes': [], 'internal_links': ['https://example.com/private']}
    store.collector.side_effect = paused
    asyncio.run(flows.execute_diagnosis_page(ident))
    with Session(store.engine) as db:
        assert db.scalar(select(func.count()).select_from(SeoPageSnapshot)) == 0
        assert db.scalar(select(func.count()).select_from(SeoSitePage)) == 1


def test_failed_discovery_requires_explicit_advisor_retry(store, monkeypatch):
    discovery = configure(store, monkeypatch)
    discovery.return_value = {'error': 'robots_unavailable'}
    ident = create(store, 'website')['task']['id']
    finish_round(store, ident)
    assert discovery.await_count == 1 and task(store, ident).params['phase'] == 'discovery_needs_attention'
    discovery.return_value = {'urls': ['https://example.com/'], 'sitemap_queue': [], 'warnings': [],
        'sitemaps_checked': [], 'queue_truncated': False, 'more_sitemaps_pending': False}
    advance(store, ident)
    assert finish_round(store, ident).status == 'done' and discovery.await_count == 2


def test_large_sitemap_resumes_after_first_batch_and_denies_other_hosts_and_ports():
    visited = []
    async def fetch(url, **kwargs):
        visited.append(url)
        assert kwargs['allowed_hosts'] == frozenset({'example.com', 'www.example.com'})
        if url.endswith('robots.txt'):
            return response(url, 'User-agent: *\nDisallow: /private')
        body = '<urlset>' + ''.join(f'<url><loc>https://example.com/p/{i}</loc></url>' for i in range(240))
        body += '<url><loc>https://foreign.test/a</loc></url><url><loc>https://example.com:8080/a</loc></url></urlset>'
        return response(url, body)
    first = asyncio.run(crawl.discover('example.com', fetcher=fetch))
    second = asyncio.run(crawl.discover('example.com', first, fetcher=fetch))
    assert len(first['urls']) == 200 and first['more_sitemaps_pending']
    assert 'https://example.com/p/239' in second['urls'] and not second['more_sitemaps_pending']
    assert not any('foreign' in v or ':8080' in v for v in first['urls'] + second['urls'])
    assert set(visited) == {'https://example.com/robots.txt', 'https://example.com/sitemap.xml'}


def test_robots_unavailable_never_fetches_sitemaps():
    fetch = AsyncMock(return_value=response('https://example.com/robots.txt', status=503, error='http_5xx'))
    assert asyncio.run(crawl.discover('example.com', fetcher=fetch))['error'] == 'robots_unavailable'
    assert fetch.await_count == 1


def test_html_policy_is_not_permission_and_malformed_sitemap_is_visible():
    fetch = AsyncMock(return_value=response('https://example.com/robots.txt', '<html>error</html>'))
    assert asyncio.run(crawl.discover('example.com', fetcher=fetch))['error'] == 'robots_unavailable'
    assert fetch.await_count == 1
    fetch = AsyncMock(side_effect=[response('https://example.com/robots.txt'),
                                  response('https://example.com/sitemap.xml', '<html>')])
    result = asyncio.run(crawl.discover('example.com', fetcher=fetch))
    assert result['warnings'] == ['sitemap_invalid'] and result['request_count'] == 2


def test_discovery_reserves_quota_before_network_and_refunds_only_known_unused_requests(store, monkeypatch):
    discovery = configure(store, monkeypatch)
    monkeypatch.setattr(flows, 'get_settings', lambda: SimpleNamespace(seo_manual_crawl_max_urls_per_tenant_per_day=5))
    ident = create(store, 'website')['task']['id']
    asyncio.run(flows.execute_discovery(ident))
    discovery.assert_not_awaited()
    assert task(store, ident).params['incremental']['error'] == 'crawl_quota_exhausted'
    monkeypatch.setattr(flows, 'get_settings', lambda: SimpleNamespace(seo_manual_crawl_max_urls_per_tenant_per_day=6))
    discovery.return_value['request_count'] = 2
    advance(store, ident)
    with Session(store.engine) as db:
        assert db.get(TenantModule, 1).module_settings['seo_daily_usage']['crawl_urls'] == 2
        assert db.scalar(select(func.count()).select_from(SeoSitePage)) == 1


@requires_pg
def test_native_postgres_claim_is_single_and_revocation_discards_discovery(monkeypatch):
    async def scenario():
        async with database() as sessions:
            async with sessions() as session:
                for model in (SeoSitePage, SeoTask, SeoPageSnapshot, SeoCrawlRun, SeoRankSnapshot):
                    await session.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
                await session.execute(text('CREATE TABLE alembic_version (version_num TEXT)'))
                await session.execute(text("INSERT INTO alembic_version VALUES ('0106_seo_content_messages')"))
                site = await session.get(SeoSite, 2)
                site.site_settings = {'seo_service_plan': {'revision': 1, 'website_incremental_enabled': True}}
                session.add(SeoTask(id=100, tenant_id=4, site_id=2, module='seo', action_type='site_diagnosis',
                    title='fixture', status='in_progress', created_by='fixture', assignee_role='seo_advisor',
                    params={'kind': 'website', 'pages': {}, 'child_task_ids': [], 'incremental': {'state': 'queued', 'max_pages': 1}},
                    created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)))
                await session.commit()
            monkeypatch.setattr(flows, 'async_session_factory', sessions)
            started, release, calls = asyncio.Event(), asyncio.Event(), []
            async def discover(*args):
                calls.append(args)
                started.set()
                await release.wait()
                return {'urls': ['https://example.com/']}
            monkeypatch.setattr(crawl, 'discover', discover)
            first = asyncio.create_task(flows.execute_discovery(100))
            await asyncio.wait_for(started.wait(), 5)
            await asyncio.gather(*(flows.execute_discovery(100) for _ in range(8)))
            assert len(calls) == 1
            async with sessions() as session:
                (await session.get(TenantModule, 1)).status = 'disabled'
                await session.commit()
            release.set()
            await first
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(SeoSitePage)) == 0
                assert (await session.get(SeoTask, 100)).params['incremental']['state'] == 'failed'
            # The same native schema also exercises actual inventory/snapshot writes.
            async with sessions() as session:
                (await session.get(TenantModule, 1)).status = 'active'
                row = await session.get(SeoTask, 100)
                row.params = {**row.params, 'incremental': {'state': 'queued', 'max_pages': 1}}
                row.baseline = {'metric_key': 'seo.site.observation_count', 'value': 0}
                await session.commit()
            monkeypatch.setattr(crawl, 'discover', AsyncMock(return_value={'urls': ['https://example.com/'],
                'sitemap_queue': [], 'warnings': [], 'sitemaps_checked': [], 'queue_truncated': False,
                'more_sitemaps_pending': False, 'request_count': 2}))
            monkeypatch.setattr(flows, 'collect_page_snapshot', AsyncMock(return_value={
                'url': 'https://example.com/', 'status_code': 200, 'issue_codes': [], 'raw_html_hash': 'c'*64,
                'internal_links': ['https://example.com/next', 'https://foreign.test/private'], 'click_depth': 0}))
            await flows.execute_discovery(100)
            await flows.execute_diagnosis_page(100)
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(SeoSitePage)) == 2
                assert await session.scalar(select(func.count()).select_from(SeoPageSnapshot)) == 1
                site, row = await session.get(SeoSite, 2), await session.get(SeoTask, 100, with_for_update=True)
                await flows.advance_service_workflow(session, site, row)
                assert row.status == 'done'
                await session.commit()
    asyncio.run(scenario())
