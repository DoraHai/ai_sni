"""Bounded site inventory discovery, with durable sitemap continuation.

Uses existing site JSONB and page inventory; never modifies a customer's site.
All production requests retain the pinned public-IP transport.
"""
import asyncio
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser

from sqlalchemy import select

from app.models.seo import SeoSitePage, SeoSiteAdvisorAssignment
from app.models.user import User
from app.models.role import Role
from app.module_scope import seo_site_is_operational
from app.seo_content_workflow import plan_for
from app.seo_service_plan import service_plan_is_paused
from app.seo_crawler import (SeoCrawlError, USER_AGENT, fetch_url,
                             normalize_crawl_url, is_html_page_url, sitemap_urls)

DISCOVERY_LIMIT = 200
INVENTORY_LIMIT = 5000
SITEMAP_LIMIT = 5
QUEUE_LIMIT = 200


def site_hosts(domain):
    host = (urlparse(normalize_crawl_url(domain)).hostname or '').lower().rstrip('.')
    root = host[4:] if host.startswith('www.') else host
    return frozenset((root, 'www.' + root))


def scoped_url(raw, hosts, *, page=True):
    try:
        value = normalize_crawl_url(raw, preserve_path=True)
        parsed = urlparse(value)
        if ((parsed.hostname or '').lower().rstrip('.') not in hosts
                or (parsed.port or (443 if parsed.scheme == 'https' else 80)) not in {80, 443}
                or len(value) > 2000 or (page and not is_html_page_url(value))):
            return None
        return value
    except (SeoCrawlError, ValueError):
        return None


async def authorized(session, site):
    return (site is not None and not service_plan_is_paused(site)
            and plan_for(site).get('website_incremental_enabled') is True
            and await seo_site_is_operational(session, site.tenant_id, site.id)
            and await session.scalar(select(SeoSiteAdvisorAssignment.id).join(User,
                User.id == SeoSiteAdvisorAssignment.advisor_user_id).join(Role, Role.id == User.role_id).where(
                SeoSiteAdvisorAssignment.tenant_id == site.tenant_id,
                SeoSiteAdvisorAssignment.site_id == site.id, SeoSiteAdvisorAssignment.active.is_(True),
                User.is_active.is_(True), User.tenant_id.is_(None) | (User.tenant_id == site.tenant_id),
                Role.permissions['seo.site'].as_string() == 'edit',
                Role.permissions['seo.content'].as_string() == 'edit').limit(1)) is not None)


async def discover(domain, cursor=None, *, fetcher=None):
    """Read policy and at most five sitemaps, resuming large maps next round.

    An unreadable robots policy is a failure, never implied permission.
    Missing sitemap is allowed: the homepage's internal links provide discovery.
    """
    fetcher = fetcher or fetch_url
    hosts = site_hosts(domain)
    seed = scoped_url('https://' + (urlparse(normalize_crawl_url(domain)).hostname or '') + '/', hosts)
    robots_url = urljoin(seed, '/robots.txt')
    requests = 1
    async with asyncio.timeout(95):
        robots = await fetcher(robots_url, allow_text=True, allowed_hosts=hosts)
        parser = RobotFileParser()
        if (robots.status_code == 200 and not robots.error_type
                and (robots.content_type or '').lower().startswith('text/plain')
                and not robots.body.lstrip('\ufeff \t\r\n').startswith('<')):
            parser.parse(robots.body.splitlines())
        elif robots.status_code in {404, 410}:
            parser.parse([])
        else:
            return {'error': 'robots_unavailable', 'request_count': requests}
        truncated = len((cursor or {}).get('sitemap_queue', [])) > QUEUE_LIMIT
        queue = [dict(item) for item in (cursor or {}).get('sitemap_queue', [])[:QUEUE_LIMIT]
                 if scoped_url(item.get('url', ''), hosts, page=False)]
        if not queue:
            roots = [urljoin(seed, '/sitemap.xml')]
            roots += [line.split(':', 1)[1].strip() for line in robots.body.splitlines()
                      if line.strip().lower().startswith('sitemap:')]
            queue = [{'url': value, 'offset': 0} for raw in dict.fromkeys(roots)
                     if (value := scoped_url(raw, hosts, page=False))]
            truncated = truncated or len(queue) > QUEUE_LIMIT
            queue = queue[:QUEUE_LIMIT]
        candidates = [seed] if parser.can_fetch(USER_AGENT, seed) else []
        checked, warnings, seen = [], [], set()
        while queue and len(checked) < SITEMAP_LIMIT and len(candidates) < DISCOVERY_LIMIT:
            item = queue.pop(0)
            target = scoped_url(item['url'], hosts, page=False)
            if not target or target in seen:
                continue
            seen.add(target)
            if not parser.can_fetch(USER_AGENT, target):
                warnings.append('sitemap_robots_blocked')
                continue
            checked.append(target)
            requests += 1
            result = await fetcher(target, allow_xml=True, allow_text=True, allowed_hosts=hosts)
            if result.status_code != 200 or result.error_type:
                if result.status_code not in {404, 410}:
                    warnings.append('sitemap_unavailable')
                continue
            try:
                pages, children = sitemap_urls(result.body, strict=True)
            except SeoCrawlError:
                warnings.append('sitemap_invalid')
                continue
            offset = max(0, int(item.get('offset') or 0))
            while offset < len(pages) and len(candidates) < DISCOVERY_LIMIT:
                raw, offset = pages[offset], offset + 1
                value = scoped_url(raw, hosts)
                if value and parser.can_fetch(USER_AGENT, value) and value not in candidates:
                    candidates.append(value)
            if offset < len(pages):
                queue.insert(0, {'url': target, 'offset': offset})
            for raw in children:
                value = scoped_url(raw, hosts, page=False)
                if value and value not in seen and all(q['url'] != value for q in queue):
                    if len(queue) < QUEUE_LIMIT:
                        queue.append({'url': value, 'offset': 0})
                    else:
                        truncated = True
        return {'urls': candidates, 'sitemap_queue': queue[:QUEUE_LIMIT], 'sitemaps_checked': checked,
                'warnings': sorted(set(warnings)), 'queue_truncated': truncated,
                'more_sitemaps_pending': bool(queue), 'error': None, 'request_count': requests}


async def register_urls(session, site, urls, *, limit=None):
    """Caller holds the site row lock; inventory is shared across all rounds."""
    hosts = site_hosts(site.canonical_domain)
    limit = DISCOVERY_LIMIT if limit is None else max(0, min(DISCOVERY_LIMIT, limit))
    rows = list(await session.scalars(select(SeoSitePage).where(
        SeoSitePage.tenant_id == site.tenant_id, SeoSitePage.site_id == site.id)))
    known = {scoped_url(row.url, hosts) for row in rows}
    count, added, limited, more = len(rows), [], len(rows) >= INVENTORY_LIMIT, False
    for raw in urls:
        value = scoped_url(raw, hosts)
        if not value or value in known:
            continue
        if count >= INVENTORY_LIMIT:
            limited = True
            break
        if len(added) >= limit:
            more = True
            break
        page = SeoSitePage(tenant_id=site.tenant_id, site_id=site.id, url=value,
                           status='pending', page_type='discovered')
        session.add(page)
        await session.flush()
        added.append(page.id)
        known.add(value)
        count += 1
    return {'added_page_ids': added, 'inventory_count': count, 'inventory_limit_reached': limited,
            'more_urls_pending': more}


def changed_fields(previous, values):
    fields = ('raw_html_hash', 'main_content_hash', 'status_code', 'final_url', 'robots_allowed', 'title', 'meta_description', 'h1_texts',
              'canonical_url', 'meta_robots', 'x_robots_tag', 'indexable', 'schema_types', 'issue_codes')
    return [key for key in fields if getattr(previous, key, None) != values.get(key)] if previous else []
