import asyncio
import inspect
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import httpx
from fastapi import HTTPException
from sqlalchemy import BigInteger, Column, Integer, JSON, MetaData, Table, create_engine
from sqlalchemy.dialects.postgresql import JSONB, dialect
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api import seo
from app.api.seo_site_diagnostics import get_image_evidence
from app.models.seo import SeoCrawlRun, SeoPageSnapshot, SeoSitePage
from app.security.auth import AuthContext, _required
from app import seo_page_audit as audit
from app.seo_crawler import FetchResult

URL = 'https://example.com/products/234'
HTML = '''<html lang="zh"><head><title>Product 234</title></head><body>
<main><h1>Product</h1><img id="product" src="/one.jpg"><img src="/two.jpg" alt="">
<img src="/three.jpg" alt="  "><img src="/four.jpg" alt="Product">
<a href="/not-authorized">Another page</a></main></body></html>'''


def response(url=URL, body=HTML, status=200, error=None):
    return FetchResult(url, url, status, [], 'text/html', body, len(body), 5, {}, error, error)


def ctx(**overrides):
    return AuthContext(**(dict(user_id=7, username='operator', tenant_id=1,
                              role_name='editor', permissions={'seo.site': 'edit'}) | overrides))


def page(**overrides):
    return SeoSitePage(**(dict(id=234, tenant_id=1, site_id=1, url=URL, status='approved',
                              title_suggestion='Keep approved title', description_suggestion='Keep description') | overrides))


def snapshot():
    return audit._snapshot(response(), URL, True)


def test_single_page_fetches_only_policy_and_target_and_preserves_image_evidence():
    fetch = AsyncMock(side_effect=[response(URL + '/robots', 'User-agent: *\nAllow: /'), response()])
    result = asyncio.run(audit.collect_page_snapshot(URL, fetcher=fetch))
    assert [call.args[0] for call in fetch.call_args_list] == ['https://example.com/robots.txt', URL]
    assert fetch.call_args_list[0].kwargs == {'allow_text': True}
    assert result['discovery_source'] == 'single_page' and result['url'] == URL
    evidence = result['image_alt_evidence']
    assert evidence['images_count'] == 4 and evidence['candidate_count'] == 3
    assert evidence['counts'] == {'missing': 1, 'empty': 1, 'whitespace': 1}
    assert evidence['items'][0]['source_url'] == 'https://example.com/one.jpg'
    assert evidence['items'][0]['section'] == 'main'
    assert evidence['items'][0]['element_id'] == 'product'
    assert 'internal_links' not in result and 'internal_link_details' not in result


@pytest.mark.parametrize('policy,expected,calls', [
    (response(body='User-agent: *\nDisallow: /products'), 'robots_blocked', 1),
    (response(status=503, error='http_5xx'), 'robots_unavailable', 1),
    (response(status=None, error='timeout'), 'robots_unavailable', 1),
    (response(body='', status=200), None, 2),
    (response(body='  \n\t', status=200), None, 2),
    (response(body='# No restrictions\n', status=200), None, 2),
    (response(body='', status=200, error='non_html'), 'robots_unavailable', 1),
    (response(status=404, error='http_4xx'), None, 2),
    (response(status=410, error='http_4xx'), None, 2),
])
def test_robots_policy_failure_is_not_bypassed(policy, expected, calls):
    fetch = AsyncMock(side_effect=[policy, response()])
    result = asyncio.run(audit.collect_page_snapshot(URL, fetcher=fetch))
    assert fetch.await_count == calls
    assert result.get('error_type') == expected
    if expected:
        assert result.get('image_alt_evidence') is None
        assert result['robots_allowed'] is (False if expected == 'robots_blocked' else None)


@pytest.mark.parametrize('failure', [
    response(status=404, error='http_4xx'), response(status=503, error='http_5xx'),
    response(status=None, error='timeout'), response(body=''),
    response(status=200, error='non_html'), response(status=302),
])
def test_failed_response_never_saves_image_evidence_from_error_html(failure):
    fetch = AsyncMock(side_effect=[response(body='User-agent: *\nAllow: /'), failure])
    result = asyncio.run(audit.collect_page_snapshot(URL, fetcher=fetch))
    assert result['error_type'] and result['image_alt_evidence'] is None


def test_overall_deadline_is_bounded(monkeypatch):
    async def slow(*args, **kwargs):
        await asyncio.sleep(1)
    monkeypatch.setattr(audit, 'SINGLE_PAGE_TIMEOUT', 0.001)
    result = asyncio.run(audit.collect_page_snapshot(URL, fetcher=slow))
    assert result['error_type'] == 'timeout' and result['image_alt_evidence'] is None


def test_default_fetch_uses_existing_pinned_crawler():
    from app.seo_crawler import fetch_url
    assert audit.fetch_url is fetch_url
    assert 'pinned_async_client' in inspect.getsource(fetch_url)
    assert '_ensure_public_host' in inspect.getsource(fetch_url)


@pytest.mark.parametrize('target,redirect', [
    ('https://example.com/products/234/', None),
    ('https://example.com/products/234', '/products/234/'),
    ('https://example.com/products/234/', '/products/234'),
    ('https://example.com/products//234/;v=2?lang=cn&x=%2F', None),
])
def test_wire_url_preserves_path_and_redirects_without_rewriting_resources(monkeypatch, target, redirect):
    from app import seo_crawler as crawler
    visited = []
    page_calls = []
    class Transport(crawler.PinnedAsyncHTTPTransport):
        async def handle_async_request(self, request):
            visited.append(str(request.url))
            if request.url.path == '/robots.txt':
                return httpx.Response(200, headers={'content-type': 'text/plain'}, text='', request=request)
            page_calls.append(str(request.url))
            if redirect and len(page_calls) == 1:
                return httpx.Response(301, headers={'location': redirect}, request=request)
            return httpx.Response(200, headers={'content-type': 'text/html'}, text=HTML, request=request)
    def client(**kwargs):
        return httpx.AsyncClient(transport=Transport(), **kwargs)
    monkeypatch.setattr(crawler, 'pinned_async_client', client)
    check = AsyncMock(return_value='93.184.216.34')
    monkeypatch.setattr(crawler, '_ensure_public_host', check)
    result = asyncio.run(audit.collect_page_snapshot(target))
    expected = [target] + ([f'https://example.com{redirect}'] if redirect else [])
    assert page_calls == expected
    assert visited == ['https://example.com/robots.txt', *expected]
    assert [call.args[0] for call in check.call_args_list] == visited
    assert result['url'] == target and result['final_url'] == expected[-1]
    assert result.get('error_type') is None
    assert result['image_alt_evidence']['candidate_count'] == 3
    row = page(status='proposed')
    audit.apply_page_snapshot(row, result, datetime.now())
    assert row.status == 'proposed' and row.title_suggestion == 'Keep approved title'


def test_robots_rules_are_checked_against_actual_trailing_slash_path():
    fetch = AsyncMock(return_value=response(body='User-agent: *\nDisallow: /products/234/'))
    result = asyncio.run(audit.collect_page_snapshot(URL + '/', fetcher=fetch))
    assert result['error_type'] == 'robots_blocked'
    fetch.assert_awaited_once()


@pytest.mark.parametrize('href', ['https://example.com:bad/a', 'https://[invalid/a', 'https://example.com:99999/a'])
@pytest.mark.parametrize('tag', ['a', 'canonical', 'alternate'])
def test_malformed_document_links_do_not_discard_image_evidence(href, tag):
    element = (f'<a href="{href}">broken</a>' if tag == 'a' else
               f'<link rel="{tag}" hreflang="en" href="{href}">')
    fetch = AsyncMock(side_effect=[response(body=''), response(body=HTML.replace('</main>', element + '</main>'))])
    result = asyncio.run(audit.collect_page_snapshot(URL, fetcher=fetch))
    assert result.get('error_type') is None
    assert result['title'] == 'Product 234'
    assert result['image_alt_evidence']['candidate_count'] == 3
    assert result['internal_links_count'] == 1
    assert result['external_links_count'] == 0
    assert result['canonical_url'] is None and result['hreflang_tags'] == []
    assert fetch.await_count == 2


@pytest.mark.parametrize('url', ['https://user:pass@example.com', 'https://example.com:bad/'])
def test_invalid_legacy_url_produces_failure_without_network(url):
    fetch = AsyncMock()
    result = asyncio.run(audit.collect_page_snapshot(url, fetcher=fetch))
    assert result['error_type'] == 'invalid_url'
    fetch.assert_not_awaited()


@pytest.mark.parametrize('status', ['approved', 'proposed', 'implemented', 'needs_fix'])
def test_success_preserves_suggestions_and_uses_seo_scan_rules(status):
    row = page(status=status)
    result = snapshot()
    audit.apply_page_snapshot(row, result, datetime(2026, 9, 3, 14))
    assert row.title_suggestion == 'Keep approved title'
    assert row.description_suggestion == 'Keep description'
    assert row.audit_score == max(0, 100 - 10 * len(result['issue_codes']))
    assert row.status == (status if status in {'approved', 'proposed'} else 'needs_fix')
    assert row.http_status == 200


@pytest.mark.parametrize('previous,retained', [('approved', True), ('proposed', False)])
def test_failure_has_no_score_and_does_not_retire_approved_suggestions(previous, retained):
    row = page(status=previous)
    audit.apply_page_snapshot(row, {'error_type': 'timeout', 'issue_codes': ['timeout']}, datetime.now())
    assert row.status == 'error' and row.audit_score is None and row.indexable is None
    assert bool(row.title_suggestion) == retained


def test_route_commits_one_observation_with_actor_site_and_tenant(monkeypatch):
    row, db = page(), AsyncMock()
    db.scalar.return_value = row
    db.add = MagicMock()
    async def assign_id():
        db.add.call_args.args[0].id = 123
    db.flush.side_effect = assign_id
    monkeypatch.setattr(seo, '_seo_site', AsyncMock())
    fetch = AsyncMock(return_value=snapshot())
    monkeypatch.setattr(seo, 'collect_page_snapshot', fetch)
    asyncio.run(seo.audit_site_page(234, 1, db, ctx(), 1))
    fetch.assert_awaited_once_with(URL)
    run, saved = [call.args[0] for call in db.add.call_args_list]
    assert isinstance(run, SeoCrawlRun) and run.max_urls == 1
    assert run.status == 'single_completed' and run.created_by == 7
    assert isinstance(saved, SeoPageSnapshot)
    assert (saved.crawl_run_id, saved.tenant_id, saved.site_id) == (123, 1, 1)
    assert saved.image_alt_evidence['candidate_count'] == 3
    sql = str(db.scalar.call_args.args[0].compile(dialect=dialect()))
    assert 'FOR UPDATE NOWAIT' in sql
    assert all(f'seo_site_pages.{name} =' in sql for name in ['id', 'tenant_id', 'site_id'])
    db.commit.assert_awaited_once()


@pytest.mark.parametrize('auth,found,site,expected', [
    (ctx(tenant_id=2), page(), 1, 403),
    (ctx(permissions={'seo.site': 'view'}), page(), 1, 403),
    (ctx(), None, 2, 404), (ctx(), page(site_id=None), None, 422),
])
def test_rejected_requests_never_fetch(monkeypatch, auth, found, site, expected):
    db = AsyncMock()
    db.scalar.return_value = found
    fetch = AsyncMock()
    monkeypatch.setattr(seo, 'collect_page_snapshot', fetch)
    with pytest.raises(HTTPException) as error:
        asyncio.run(seo.audit_site_page(234, 1, db, auth, site))
    assert error.value.status_code == expected
    fetch.assert_not_awaited()
    db.commit.assert_not_awaited()


def test_concurrent_request_is_rejected_before_fetch(monkeypatch):
    original = Exception('locked')
    original.sqlstate = '55P03'
    db = AsyncMock()
    db.scalar.side_effect = DBAPIError('select', {}, original)
    fetch = AsyncMock()
    monkeypatch.setattr(seo, 'collect_page_snapshot', fetch)
    with pytest.raises(HTTPException) as error:
        asyncio.run(seo.audit_site_page(234, 1, db, ctx(), 1))
    assert error.value.status_code == 409
    fetch.assert_not_awaited()
    db.rollback.assert_awaited_once()


def test_route_failure_commits_failure_before_returning_422(monkeypatch):
    db = AsyncMock()
    db.scalar.return_value = page()
    monkeypatch.setattr(seo, '_seo_site', AsyncMock())
    monkeypatch.setattr(seo, 'collect_page_snapshot', AsyncMock(return_value={
        'url': URL, 'error_type': 'timeout', 'image_alt_evidence': None,
    }))
    save = AsyncMock()
    monkeypatch.setattr(seo, 'save_page_snapshot', save)
    with pytest.raises(HTTPException) as error:
        asyncio.run(seo.audit_site_page(234, 1, db, ctx(), 1))
    assert error.value.status_code == 422
    save.assert_awaited_once()
    db.commit.assert_awaited_once()


def test_site_ownership_check_precedes_network(monkeypatch):
    db = AsyncMock()
    db.scalar.return_value = page()
    monkeypatch.setattr(seo, '_seo_site', AsyncMock(side_effect=HTTPException(404, 'site missing')))
    fetch = AsyncMock()
    monkeypatch.setattr(seo, 'collect_page_snapshot', fetch)
    with pytest.raises(HTTPException):
        asyncio.run(seo.audit_site_page(234, 1, db, ctx(), 1))
    fetch.assert_not_awaited()
    db.commit.assert_not_awaited()


def test_full_site_request_cannot_return_a_single_run_by_id(monkeypatch):
    monkeypatch.setattr(seo, '_seo_site', AsyncMock())
    db = AsyncMock()
    db.scalars.return_value = []
    result = asyncio.run(seo.list_seo_crawl_runs(1, 1, 88, 10, db))
    assert result == {'runs': [], 'snapshots': []}
    db.scalars.assert_awaited_once()


def test_route_has_subscription_and_edit_guard():
    path = '/api/v1/seo/site-pages/{page_id}/audit'
    route = next(r for r in seo.router.routes if r.path == path and 'POST' in r.methods)
    assert seo.require_seo_module_access in [d.call for d in route.dependant.dependencies]
    assert _required('/api/v1/seo/site-pages/234/audit', 'POST') == ({'seo.site'}, True)


def test_single_runs_excluded_from_full_site_list_and_overview():
    assert 'SeoCrawlRun.max_urls > 1' in inspect.getsource(seo.list_seo_crawl_runs)
    assert 'SeoCrawlRun.max_urls > 1' in inspect.getsource(seo.seo_overview)


class AsyncFacade:
    """Run ORM persistence against an isolated SQLite DB, not a mocked store."""
    def __init__(self, session):
        self.session = session

    def add(self, row):
        self.session.add(row)

    async def scalar(self, statement):
        return self.session.scalar(statement)

    async def scalars(self, statement):
        return self.session.scalars(statement)

    async def flush(self):
        self.session.flush()

    async def commit(self):
        self.session.commit()

    async def rollback(self):
        self.session.rollback()

    async def refresh(self, row):
        self.session.refresh(row)


def evidence_engine(tmp_path):
    metadata = MetaData()
    for model in [SeoSitePage, SeoCrawlRun, SeoPageSnapshot]:
        table = model.__table__.to_metadata(metadata)
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
            elif isinstance(column.type, BigInteger):
                column.type = Integer()
    for table in list(metadata.tables.values()):
        for fk in table.foreign_keys:
            name = fk.target_fullname.split('.')[0]
            if name not in metadata.tables:
                columns = [Column('id', Integer, primary_key=True)]
                if name == 'seo_sites':
                    columns.append(Column('tenant_id', Integer))
                Table(name, metadata, *columns)
    engine = create_engine(f'sqlite:///{tmp_path / "evidence.db"}')
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(metadata.tables['seo_sites'].insert().values(id=1, tenant_id=1))
    return engine


def test_evidence_survives_new_session_and_later_failure_hides_old_success(tmp_path):
    engine = evidence_engine(tmp_path)
    try:
        with Session(engine) as db:
            row = page()
            db.add(row)
            db.flush()
            asyncio.run(audit.save_page_snapshot(AsyncFacade(db), row, snapshot(), 7, datetime.now()))
            db.commit()
        with Session(engine) as db:
            row = db.get(SeoSitePage, 234)
            changed = snapshot() | {'title': 'This transaction must roll back'}
            asyncio.run(audit.save_page_snapshot(AsyncFacade(db), row, changed, 7, datetime.now()))
            db.flush()
            db.rollback()
        with Session(engine) as db:
            assert db.query(SeoPageSnapshot).count() == 1
            assert db.query(SeoCrawlRun).count() == 1
            assert db.get(SeoSitePage, 234).title == 'Product 234'
            result = asyncio.run(get_image_evidence(1, 1, 234, ctx(), AsyncFacade(db)))
            assert result['evidence']['counts'] == {'missing': 1, 'empty': 1, 'whitespace': 1}
            assert result['fetched_at'].endswith('+08:00')
            row = db.get(SeoSitePage, 234)
            assert row.title_suggestion == 'Keep approved title'
            failed = audit._snapshot(response(status=None, error='timeout'), URL, True)
            asyncio.run(audit.save_page_snapshot(AsyncFacade(db), row, failed, 7, datetime.now()))
            db.commit()
        with Session(engine) as db:
            result = asyncio.run(get_image_evidence(1, 1, 234, ctx(), AsyncFacade(db)))
            assert result['fetch_error'] == 'timeout' and result['evidence'] is None
            assert db.query(SeoPageSnapshot).count() == 2
            assert db.query(SeoCrawlRun).filter(SeoCrawlRun.max_urls > 1).count() == 0
    finally:
        engine.dispose()


def test_pending_retry_after_single_failure_persists_fresh_evidence(tmp_path, monkeypatch):
    engine = evidence_engine(tmp_path)
    monkeypatch.setattr(seo, '_tenant', AsyncMock())
    monkeypatch.setattr(seo, '_seo_site', AsyncMock())
    collect = AsyncMock(side_effect=[
        audit._snapshot(response(body='', status=None, error='timeout'), URL, True), snapshot(),
    ])
    monkeypatch.setattr(seo, 'collect_page_snapshot', collect)
    try:
        with Session(engine) as db:
            db.add(page(status='pending', title=None))
            db.commit()
            with pytest.raises(HTTPException) as error:
                asyncio.run(seo.audit_site_page(234, 1, AsyncFacade(db), ctx(), 1))
            assert error.value.status_code == 422
        with Session(engine) as db:
            result = asyncio.run(seo.audit_pending_site_pages(1, 1, 10, AsyncFacade(db), ctx()))
            assert result == {'selected': 1, 'completed': 1, 'failed': [], 'skipped': 0, 'deferred': 0, 'remaining': 0}
        with Session(engine) as db:
            evidence = asyncio.run(get_image_evidence(1, 1, 234, ctx(), AsyncFacade(db)))
            assert evidence['fetch_error'] is None
            assert evidence['evidence']['candidate_count'] == 3
            row = db.get(SeoSitePage, 234)
            assert row.http_status == 200 and row.last_error is None
            assert db.query(SeoPageSnapshot).count() == 2
            assert db.query(SeoCrawlRun).count() == 2
    finally:
        engine.dispose()


def test_pending_batch_keeps_success_when_later_page_fails(tmp_path, monkeypatch):
    engine = evidence_engine(tmp_path)
    monkeypatch.setattr(seo, '_tenant', AsyncMock())
    monkeypatch.setattr(seo, '_seo_site', AsyncMock())
    first, second = URL, URL + '-second'
    collect = AsyncMock(side_effect=[snapshot(), audit._snapshot(response(status=None, error='timeout'), second, True)])
    monkeypatch.setattr(seo, 'collect_page_snapshot', collect)
    try:
        with Session(engine) as db:
            db.add_all([page(status='pending'), page(id=235, url=second, status='pending'),
                        page(id=236, site_id=2, status='pending')])
            db.commit()
            result = asyncio.run(seo.audit_pending_site_pages(1, 1, 10, AsyncFacade(db), ctx()))
            assert result['selected'] == 2 and result['completed'] == 1
            assert [item['page_id'] for item in result['failed']] == [235]
        with Session(engine) as db:
            assert db.get(SeoSitePage, 234).http_status == 200
            assert db.get(SeoSitePage, 235).status == 'error'
            assert db.get(SeoSitePage, 236).status == 'pending'
            assert db.query(SeoPageSnapshot).count() == 2
            assert db.query(SeoPageSnapshot).filter(SeoPageSnapshot.site_id == 2).count() == 0
        assert [call.args[0] for call in collect.call_args_list] == [first, second]
    finally:
        engine.dispose()


@pytest.mark.parametrize('auth', [ctx(tenant_id=2), ctx(permissions={'seo.site': 'view'})])
def test_pending_batch_rejects_scope_before_select_or_fetch(auth, monkeypatch):
    db = AsyncMock()
    collect = AsyncMock()
    monkeypatch.setattr(seo, 'collect_page_snapshot', collect)
    with pytest.raises(HTTPException) as error:
        asyncio.run(seo.audit_pending_site_pages(1, 1, 10, db, auth))
    assert error.value.status_code == 403
    db.scalars.assert_not_awaited()
    collect.assert_not_awaited()


def test_pending_batch_skips_page_completed_since_selection(monkeypatch):
    db = AsyncMock()
    db.scalar.return_value = page(title='Already processed', status='needs_fix')
    collect = AsyncMock()
    monkeypatch.setattr(seo, 'collect_page_snapshot', collect)
    result = asyncio.run(seo._audit_site_page_observation(234, 1, db, ctx(), 1, pending_only=True))
    assert result is None
    collect.assert_not_awaited()
    db.rollback.assert_awaited_once()


def test_pending_batch_budget_defers_remaining_without_fetching(monkeypatch):
    db = AsyncMock()
    db.scalars.return_value = [234, 235, 236]
    db.scalar.return_value = 2
    monkeypatch.setattr(seo, '_tenant', AsyncMock())
    monkeypatch.setattr(seo, '_seo_site', AsyncMock())
    monkeypatch.setattr(seo, 'monotonic', MagicMock(side_effect=[0, 0, 71]))
    audit_one = AsyncMock(return_value=page())
    monkeypatch.setattr(seo, '_audit_site_page_observation', audit_one)
    result = asyncio.run(seo.audit_pending_site_pages(1, 1, 3, db, ctx()))
    assert result['completed'] == 1 and result['deferred'] == 2 and result['remaining'] == 2
    audit_one.assert_awaited_once()


@pytest.mark.parametrize('failure', [HTTPException(409, 'busy'), RuntimeError('internal detail')])
def test_pending_batch_isolates_lock_and_unexpected_errors(monkeypatch, failure):
    db = AsyncMock()
    db.scalars.return_value = [234, 235]
    db.scalar.return_value = 1
    monkeypatch.setattr(seo, '_tenant', AsyncMock())
    monkeypatch.setattr(seo, '_seo_site', AsyncMock())
    audit_one = AsyncMock(side_effect=[failure, page(id=235)])
    monkeypatch.setattr(seo, '_audit_site_page_observation', audit_one)
    result = asyncio.run(seo.audit_pending_site_pages(1, 1, 2, db, ctx()))
    assert result['completed'] == 1
    assert result['failed'][0]['page_id'] == 234
    assert 'internal detail' not in result['failed'][0]['message']
    assert audit_one.await_count == 2
    db.rollback.assert_awaited_once()
