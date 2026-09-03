"""Single-page SEO observations; never discover or enqueue other pages."""

import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

from app.models.seo import SeoCrawlRun, SeoPageSnapshot
from app.seo_crawler import (
    FetchResult, SeoCrawlError, USER_AGENT, analyze_html, fetch_url, normalize_crawl_url,
)

SINGLE_PAGE_TIMEOUT = 40


async def collect_page_snapshot(url, *, fetcher=None):
    """Read robots and exactly one page (including safe HTTP redirects).

    No sitemap, link traversal, image requests, AI, or publishing. Failed
    observations are persisted too, so stale success is never shown as current.
    """
    fetcher = fetcher or fetch_url
    try:
        target = normalize_crawl_url(url, preserve_path=True)
    except (SeoCrawlError, ValueError):
        return _snapshot(FetchResult(url, url, None, [], None, '', None, None, {},
                                     'invalid_url', '页面地址无效，未发起抓取'), url, None)
    allowed = None
    try:
        async with asyncio.timeout(SINGLE_PAGE_TIMEOUT):
            robots_url = urljoin(target, '/robots.txt')
            robots = await fetcher(robots_url, allow_text=True)
            if robots.status_code == 200 and not robots.error_type:
                # A successfully read empty file has no disallow rules; this
                # differs from a timeout/non-text/error response with no body.
                parser = RobotFileParser()
                parser.parse(robots.body.splitlines())
                allowed = parser.can_fetch(USER_AGENT, target)
            elif robots.status_code in (404, 410):
                allowed = True
            else:
                # A transient/unreadable policy is not permission to crawl.
                result = FetchResult(target, target, None, [], None, '', None, None, {},
                                     'robots_unavailable', 'robots.txt 无法核实，未抓取目标页面')
                return _snapshot(result, url, None)
            if not allowed:
                result = FetchResult(target, target, None, [], None, '', None, None, {},
                                     'robots_blocked', 'robots.txt 禁止抓取此页面')
            else:
                result = await fetcher(target)
    except TimeoutError:
        result = FetchResult(target, target, None, [], None, '', None, None, {},
                             'timeout', '单页检测超时')
    return _snapshot(result, url, allowed)


def _snapshot(result, original_url, allowed):
    values = analyze_html(result, robots_allowed=allowed is not False)
    values['robots_allowed'] = allowed
    # Both main and production parsers can return auxiliary link data. It is
    # deliberately not enqueued or inserted into the link-monitoring tables.
    values.pop('internal_links', None)
    values.pop('internal_link_details', None)
    values.update(url=original_url, discovery_source='single_page', click_depth=0)
    if result.status_code is None or not 200 <= result.status_code < 300:
        values['error_type'] = values.get('error_type') or 'http_status_unavailable'
    if values.get('error_type'):
        values['image_alt_evidence'] = None
        if values['error_type'] not in values.get('issue_codes', []):
            values.setdefault('issue_codes', []).append(values['error_type'])
    return values


def apply_page_snapshot(page, values, checked_at):
    """Refresh SEO facts using the same issue/score contract as site scans."""
    previous = page.status
    issues = values.get('issue_codes') or []
    failed = bool(values.get('error_type'))
    page.http_status = values.get('status_code')
    page.issue_codes = issues
    page.last_checked_at = checked_at
    page.last_error = (values.get('fetch_error') or values.get('error_type')) if failed else None
    if failed:
        page.audit_score = None
        page.indexable = None
        page.status = 'error'
        # Match production: retire only unconfirmed suggestions after failure.
        if previous == 'proposed':
            page.title_suggestion = None
            page.description_suggestion = None
        return
    page.title = values.get('title')
    page.meta_description = values.get('meta_description')
    page.h1 = (values.get('h1_texts') or [None])[0]
    page.canonical = values.get('canonical_url')
    page.indexable = values.get('indexable')
    page.content_units = values.get('word_count')
    page.audit_score = max(0, 100 - len(issues) * 10)
    if previous in {'proposed', 'approved'}:
        page.status = previous
    elif issues:
        page.status = 'needs_fix'
    else:
        page.status = 'verified' if previous in {'implemented', 'verified'} else 'healthy'


async def save_page_snapshot(session, page, values, actor_id, started_at):
    """Run + snapshot + current facts commit together in the caller transaction."""
    checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
    failed = bool(values.get('error_type'))
    blocked = values.get('error_type') == 'robots_blocked'
    run = SeoCrawlRun(
        tenant_id=page.tenant_id, site_id=page.site_id, seed_url=page.url,
        # Explicit single-page provenance; full-site selectors also require
        # max_urls > 1. Per-page history may still compare these observations.
        status='single_failed' if failed else 'single_completed', max_urls=1,
        discovered_count=1, fetched_count=int(not failed),
        failed_count=int(failed and not blocked), blocked_count=int(blocked),
        issue_count=len(values.get('issue_codes') or []),
        error_summary=values.get('fetch_error') or values.get('error_type'), started_at=started_at,
        completed_at=checked_at, created_by=actor_id,
    )
    session.add(run)
    await session.flush()
    snapshot = SeoPageSnapshot(
        tenant_id=page.tenant_id, site_id=page.site_id, crawl_run_id=run.id,
        # Existing snapshot timestamps are naive CST. Use observation time,
        # not transaction-start CURRENT_TIMESTAMP, for correct latest ordering.
        fetched_at=(checked_at + timedelta(hours=8)), **values,
    )
    session.add(snapshot)
    apply_page_snapshot(page, values, checked_at)
    return snapshot
