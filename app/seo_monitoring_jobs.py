"""Bounded scheduled monitoring for registered SEO competitors and backlinks."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from sqlalchemy import or_, select

from app.config import get_settings
from app.database import async_session_factory
from app.models import SeoBacklink, SeoCompetitor, SeoCompetitorEvent
from app.models.seo import SeoCrawlRun
from app.seo_competitor import CompetitorCollectionError, collect_competitor_content
from app.seo_crawler import fetch_url
from app.seo_serp import canonical_url
from app.seo_usage_limits import refund_seo_usage


logger = logging.getLogger(__name__)


def backlink_present(body: str, source_url: str, target_url: str) -> bool:
    target = canonical_url(target_url)
    soup = BeautifulSoup(body, "html.parser")
    return any(
        canonical_url(urljoin(source_url, str(node.get("href") or ""))) == target
        for node in soup.select("a[href]")
    )


async def collect_scheduled_competitors() -> dict[str, int]:
    settings = get_settings()
    cutoff = datetime.utcnow() - timedelta(hours=20)
    async with async_session_factory() as session:
        rows = list(
            await session.scalars(
                select(SeoCompetitor)
                .where(
                    SeoCompetitor.status == "active",
                    SeoCompetitor.site_id.is_not(None),
                    or_(SeoCompetitor.last_checked_at.is_(None), SeoCompetitor.last_checked_at < cutoff),
                )
                .order_by(SeoCompetitor.last_checked_at.asc().nullsfirst(), SeoCompetitor.id)
                .limit(max(1, settings.seo_competitor_scheduler_max_per_run))
            )
        )
    checked = created = failed = 0
    for candidate in rows:
        checked += 1
        try:
            collection = await collect_competitor_content(candidate.domain)
            async with async_session_factory() as session:
                row = await session.get(SeoCompetitor, candidate.id)
                if row is None or row.status != "active" or row.site_id is None:
                    continue
                existing = list(
                    await session.scalars(
                        select(SeoCompetitorEvent).where(
                            SeoCompetitorEvent.tenant_id == row.tenant_id,
                            SeoCompetitorEvent.site_id == row.site_id,
                            SeoCompetitorEvent.competitor_id == row.id,
                            SeoCompetitorEvent.event_type == "content",
                        )
                    )
                )
                known = {item.url for item in existing}
                baseline = not existing
                for page in collection.pages:
                    if page.url in known:
                        continue
                    session.add(
                        SeoCompetitorEvent(
                            tenant_id=row.tenant_id,
                            site_id=row.site_id,
                            competitor_id=row.id,
                            event_type="content",
                            title=page.title,
                            url=page.url,
                            source_url=f"https://{row.domain}/",
                            summary="首次自动采集基线" if baseline else "自动采集发现的新内容",
                        )
                    )
                    known.add(page.url)
                    created += 1
                row.last_checked_at = datetime.utcnow()
                await session.commit()
        except CompetitorCollectionError as exc:
            failed += 1
            logger.warning(
                "[SEO][COMPETITOR][scheduled] id=%s code=%s timeout_phase=%s elapsed_ms=%s",
                candidate.id,
                exc.code,
                exc.timeout_phase,
                exc.elapsed_ms,
            )
    return {"checked": checked, "created": created, "failed": failed}


async def verify_scheduled_backlinks() -> dict[str, int]:
    settings = get_settings()
    cutoff = datetime.utcnow() - timedelta(hours=20)
    async with async_session_factory() as session:
        rows = list(
            await session.scalars(
                select(SeoBacklink)
                .where(
                    SeoBacklink.status.in_(["active", "lost"]),
                    or_(SeoBacklink.last_checked_at.is_(None), SeoBacklink.last_checked_at < cutoff),
                )
                .order_by(SeoBacklink.last_checked_at.asc().nullsfirst(), SeoBacklink.id)
                .limit(max(1, settings.seo_backlink_scheduler_max_per_run))
            )
        )
    checked = found = lost = failed = 0
    for candidate in rows:
        result = await fetch_url(candidate.source_url)
        if result.error_type or not result.body:
            failed += 1
            continue
        checked += 1
        present = backlink_present(result.body, result.final_url, candidate.target_url)
        async with async_session_factory() as session:
            row = await session.get(SeoBacklink, candidate.id)
            if row is None:
                continue
            row.last_checked_at = datetime.utcnow()
            if present:
                row.status = "active"
                row.last_seen_at = row.last_checked_at
                row.missing_checks = 0
                found += 1
            else:
                row.missing_checks = (row.missing_checks or 0) + 1
                if row.missing_checks >= 2:
                    row.status = "lost"
                    lost += 1
            await session.commit()
    return {"checked": checked, "found": found, "lost": lost, "failed": failed}


async def fail_stale_crawl_runs() -> dict[str, int]:
    """Release crawl locks and same-day quota after a worker dies mid-crawl."""
    cutoff = datetime.utcnow() - timedelta(hours=2)
    async with async_session_factory() as session:
        rows = list(
            await session.scalars(
                select(SeoCrawlRun).where(
                    SeoCrawlRun.status.in_(["queued", "running"]),
                    SeoCrawlRun.started_at < cutoff,
                )
            )
        )
        refunds = [(row.tenant_id, row.max_urls) for row in rows]
        for row in rows:
            row.status = "failed"
            row.completed_at = datetime.utcnow()
            row.error_summary = "扫描工作进程中断，已释放任务锁和配额，可重新扫描"
        await session.commit()
    for tenant_id, max_urls in refunds:
        async with async_session_factory() as session:
            await refund_seo_usage(session, tenant_id, "crawl_urls", max_urls)
    return {"failed": len(rows)}
