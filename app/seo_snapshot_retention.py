"""Bounded retention for single-page SEO audit evidence.

Human image-remediation records are immutable retention anchors: a snapshot
referenced by any draft or approved review is never selected for deletion.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, exists, func, select

from app.config import get_settings
from app.database import async_session_factory
from app.models.seo import SeoCrawlRun, SeoImageAltReview, SeoPageSnapshot


logger = logging.getLogger(__name__)
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def retention_candidate_ids(*, cutoff: datetime, min_per_url: int, batch_size: int):
    """Return a bounded query for old, unreviewed, non-recent snapshots."""
    ranked = select(
        SeoPageSnapshot.id.label("snapshot_id"),
        SeoPageSnapshot.fetched_at.label("fetched_at"),
        func.row_number().over(
            partition_by=(
                SeoPageSnapshot.tenant_id,
                SeoPageSnapshot.site_id,
                SeoPageSnapshot.url,
            ),
            order_by=(
                SeoPageSnapshot.fetched_at.desc(),
                SeoPageSnapshot.id.desc(),
            ),
        ).label("recency_rank"),
    ).where(SeoPageSnapshot.discovery_source == "single_page").subquery()
    return (
        select(ranked.c.snapshot_id)
        .where(
            ranked.c.fetched_at < cutoff,
            ranked.c.recency_rank > min_per_url,
            ~exists().where(
                SeoImageAltReview.snapshot_id == ranked.c.snapshot_id
            ),
        )
        .order_by(ranked.c.fetched_at, ranked.c.snapshot_id)
        .limit(batch_size)
    )


async def prune_old_single_page_snapshots() -> dict[str, int]:
    """Delete one bounded batch; never delete reviewed or recent evidence."""
    settings = get_settings()
    retention_days = max(1, int(settings.seo_snapshot_retention_days))
    min_per_url = max(1, int(settings.seo_snapshot_retention_min_per_url))
    batch_size = max(1, int(settings.seo_snapshot_retention_batch_size))
    # SeoPageSnapshot.fetched_at follows the existing naive-CST storage
    # contract. Compare like with like so retention is not shifted by 8 hours.
    cutoff = datetime.now(_SHANGHAI_TZ).replace(tzinfo=None) - timedelta(
        days=retention_days
    )
    candidate_ids = retention_candidate_ids(
        cutoff=cutoff,
        min_per_url=min_per_url,
        batch_size=batch_size,
    )

    async with async_session_factory() as session:
        deleted_run_ids = list(await session.scalars(
            delete(SeoPageSnapshot)
            .where(
                SeoPageSnapshot.id.in_(candidate_ids),
                ~exists().where(
                    SeoImageAltReview.snapshot_id == SeoPageSnapshot.id
                ),
            )
            .returning(SeoPageSnapshot.crawl_run_id)
            .execution_options(synchronize_session=False)
        ))
        deleted_runs = 0
        if deleted_run_ids:
            result = await session.execute(
                delete(SeoCrawlRun).where(
                    SeoCrawlRun.id.in_(set(deleted_run_ids)),
                    ~exists().where(
                        SeoPageSnapshot.crawl_run_id == SeoCrawlRun.id
                    ),
                )
                .execution_options(synchronize_session=False)
            )
            deleted_runs = max(0, int(result.rowcount or 0))
        await session.commit()

    outcome = {
        "snapshots": len(deleted_run_ids),
        "crawl_runs": deleted_runs,
    }
    if deleted_run_ids:
        logger.info("[scheduler][SEO] 单页快照保留清理完成 totals=%s", outcome)
    return outcome
