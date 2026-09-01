"""Bounded scheduled monitoring for registered SEO competitors and backlinks."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from sqlalchemy import or_, select

from app.config import get_settings
from app.database import async_session_factory
from app.module_scope import list_active_module_tenants
from app.models import SeoBacklink, SeoCompetitor, SeoCompetitorEvent
from app.models.seo import SeoCrawlRun
from app.seo_automation_runs import finish_automation_run, start_automation_run
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
        entitled_tenant_ids = [
            tenant.id for tenant in await list_active_module_tenants(session, "seo")
        ]
        if not entitled_tenant_ids:
            return {"checked": 0, "created": 0, "failed": 0}
        rows = list(
            await session.scalars(
                select(SeoCompetitor)
                .where(
                    SeoCompetitor.tenant_id.in_(entitled_tenant_ids),
                    SeoCompetitor.status == "active",
                    SeoCompetitor.site_id.is_not(None),
                    or_(SeoCompetitor.last_checked_at.is_(None), SeoCompetitor.last_checked_at < cutoff),
                )
                .order_by(SeoCompetitor.last_checked_at.asc().nullsfirst(), SeoCompetitor.id)
                .limit(max(1, settings.seo_competitor_scheduler_max_per_run))
            )
        )
    checked = created = failed = 0
    by_tenant: dict[int, list[SeoCompetitor]] = defaultdict(list)
    for candidate in rows:
        by_tenant[int(candidate.tenant_id)].append(candidate)
    for tenant_id, candidates in by_tenant.items():
        run_id = await start_automation_run(
            tenant_id=tenant_id,
            job_type="competitor",
            planned_count=len(candidates),
        )
        tenant_success = tenant_failed = tenant_skipped = 0
        errors: list[str] = []
        for candidate in candidates:
            checked += 1
            try:
                collection = await collect_competitor_content(candidate.domain)
                async with async_session_factory() as session:
                    row = await session.get(SeoCompetitor, candidate.id)
                    if row is None or row.status != "active" or row.site_id is None:
                        tenant_skipped += 1
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
                tenant_success += 1
            except CompetitorCollectionError as exc:
                failed += 1
                tenant_failed += 1
                errors.append(f"{candidate.id}:{exc.code}")
                logger.warning(
                    "[SEO][COMPETITOR][scheduled] id=%s code=%s timeout_phase=%s elapsed_ms=%s",
                    candidate.id,
                    exc.code,
                    exc.timeout_phase,
                    exc.elapsed_ms,
                )
            except Exception as exc:  # noqa: BLE001
                failed += 1
                tenant_failed += 1
                errors.append(f"{candidate.id}:{type(exc).__name__}")
                logger.exception(
                    "[SEO][COMPETITOR][scheduled] unexpected failure id=%s",
                    candidate.id,
                )
        await finish_automation_run(
            run_id,
            planned_count=len(candidates),
            success_count=tenant_success,
            failed_count=tenant_failed,
            skipped_count=tenant_skipped,
            error_summary="; ".join(errors),
        )
    return {"checked": checked, "created": created, "failed": failed}


async def verify_scheduled_backlinks() -> dict[str, int]:
    settings = get_settings()
    cutoff = datetime.utcnow() - timedelta(hours=20)
    async with async_session_factory() as session:
        entitled_tenant_ids = [
            tenant.id for tenant in await list_active_module_tenants(session, "seo")
        ]
        if not entitled_tenant_ids:
            return {"checked": 0, "found": 0, "lost": 0, "failed": 0}
        rows = list(
            await session.scalars(
                select(SeoBacklink)
                .where(
                    SeoBacklink.tenant_id.in_(entitled_tenant_ids),
                    SeoBacklink.status.in_(["active", "lost"]),
                    or_(SeoBacklink.last_checked_at.is_(None), SeoBacklink.last_checked_at < cutoff),
                )
                .order_by(SeoBacklink.last_checked_at.asc().nullsfirst(), SeoBacklink.id)
                .limit(max(1, settings.seo_backlink_scheduler_max_per_run))
            )
        )
    checked = found = lost = failed = 0
    by_tenant: dict[int, list[SeoBacklink]] = defaultdict(list)
    for candidate in rows:
        by_tenant[int(candidate.tenant_id)].append(candidate)
    for tenant_id, candidates in by_tenant.items():
        run_id = await start_automation_run(
            tenant_id=tenant_id,
            job_type="backlink",
            planned_count=len(candidates),
        )
        tenant_success = tenant_failed = tenant_skipped = 0
        errors: list[str] = []
        for candidate in candidates:
            try:
                result = await fetch_url(candidate.source_url)
                if result.error_type or not result.body:
                    failed += 1
                    tenant_failed += 1
                    errors.append(f"{candidate.id}:{result.error_type or 'empty_response'}")
                    continue
                checked += 1
                present = backlink_present(result.body, result.final_url, candidate.target_url)
                async with async_session_factory() as session:
                    row = await session.get(SeoBacklink, candidate.id)
                    if row is None:
                        tenant_skipped += 1
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
                tenant_success += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                tenant_failed += 1
                errors.append(f"{candidate.id}:{type(exc).__name__}")
                logger.exception(
                    "[SEO][BACKLINK][scheduled] unexpected failure id=%s",
                    candidate.id,
                )
        await finish_automation_run(
            run_id,
            planned_count=len(candidates),
            success_count=tenant_success,
            failed_count=tenant_failed,
            skipped_count=tenant_skipped,
            error_summary="; ".join(errors),
        )
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
