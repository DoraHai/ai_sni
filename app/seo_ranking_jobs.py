"""Background jobs owned exclusively by the independent SEO service."""

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.config import get_settings
from app.database import async_session_factory
from app.models.seo import SeoKeywordAsset, SeoRankSnapshot
from app.module_scope import list_active_module_tenants
from app.process_lock import acquire_file_lock, release_file_lock
from app.seo_rank_limits import SEO_RANK_COLLECTION_LOCK_PATH

logger = logging.getLogger(__name__)

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
def _chunks(values: list[int], size: int) -> list[list[int]]:
    size = max(1, size)
    return [values[index : index + size] for index in range(0, len(values), size)]


def _limited_batches(values: list[int], batch_size: int, remaining: int) -> list[list[int]]:
    """Build batches without ever exceeding the remaining provider-request budget."""
    if remaining <= 0:
        return []
    limited = values[:remaining]
    return _chunks(limited, batch_size)


def _group_keyword_ids_by_site(
    rows: list[tuple[int, int | None]],
) -> list[tuple[int, list[int]]]:
    """Group assigned keywords defensively; unassigned rows are never collected."""
    grouped: dict[int, list[int]] = {}
    for keyword_id, site_id in rows:
        if site_id is None:
            continue
        grouped.setdefault(site_id, []).append(keyword_id)
    return list(grouped.items())


def _local_day_start_utc(now: datetime | None = None) -> datetime:
    """Return Shanghai midnight as naive UTC for the database DateTime fields."""
    local_now = now or datetime.now(_SHANGHAI_TZ)
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_start.astimezone(timezone.utc).replace(tzinfo=None)


async def collect_daily_seo_rankings() -> None:
    """Collect daily Baidu desktop/mobile rankings within explicit hard limits."""
    settings = get_settings()
    if not settings.seo_rank_scheduler_enabled:
        logger.info("[scheduler][SEO] 自动排名采集已关闭")
        return

    lock_fh = acquire_file_lock(SEO_RANK_COLLECTION_LOCK_PATH)
    if lock_fh is None:
        logger.info("[scheduler][SEO] 另一排名采集任务正在运行，本次跳过")
        return

    # Delayed import keeps the job module independent from route initialization.
    from app.api.seo import collect_rank_serp_for_tenant

    max_keywords = max(1, settings.seo_rank_scheduler_max_keywords_per_tenant)
    max_requests = max(1, settings.seo_rank_scheduler_max_requests_per_run)
    batch_size = max(1, settings.seo_rank_scheduler_batch_size)
    batch_captured_at = datetime.utcnow()
    day_start_utc = _local_day_start_utc()
    totals = {
        "tenants": 0,
        "keywords": 0,
        "requests": 0,
        "snapshots": 0,
        "serp_results": 0,
        "errors": 0,
        "skipped_pairs": 0,
        "capped_tenants": 0,
        "unassigned_keywords": 0,
    }
    try:
        async with async_session_factory() as session:
            entitled_tenant_ids = [
                tenant.id
                for tenant in await list_active_module_tenants(session, "seo")
            ]
            if not entitled_tenant_ids:
                logger.info("[scheduler][SEO] 没有已开通且有效的 SEO 客户，本次跳过")
                return
            unassigned_rows = (
                await session.execute(
                    select(SeoKeywordAsset.tenant_id, func.count())
                    .where(
                        SeoKeywordAsset.tenant_id.in_(entitled_tenant_ids),
                        SeoKeywordAsset.status == "active",
                        SeoKeywordAsset.site_id.is_(None),
                    )
                    .group_by(SeoKeywordAsset.tenant_id)
                    .order_by(SeoKeywordAsset.tenant_id)
                )
            ).all()
            for tenant_id, count in unassigned_rows:
                unassigned_count = int(count)
                totals["unassigned_keywords"] += unassigned_count
                logger.warning(
                    "[scheduler][SEO] 客户 %s 有 %s 个启用关键词未关联网站，已跳过",
                    tenant_id,
                    unassigned_count,
                )
            tenant_ids = list(
                await session.scalars(
                    select(SeoKeywordAsset.tenant_id)
                    .where(
                        SeoKeywordAsset.tenant_id.in_(entitled_tenant_ids),
                        SeoKeywordAsset.status == "active",
                        SeoKeywordAsset.site_id.is_not(None),
                    )
                    .distinct()
                    .order_by(SeoKeywordAsset.tenant_id)
                )
            )
            for tenant_id in tenant_ids:
                if totals["requests"] >= max_requests:
                    break
                selected_rows = (
                    await session.execute(
                        select(SeoKeywordAsset.id, SeoKeywordAsset.site_id)
                        .where(
                            SeoKeywordAsset.tenant_id == tenant_id,
                            SeoKeywordAsset.status == "active",
                            SeoKeywordAsset.site_id.is_not(None),
                        )
                        .order_by(SeoKeywordAsset.priority, SeoKeywordAsset.id)
                        .limit(max_keywords + 1)
                    )
                ).all()
                if not selected_rows:
                    continue
                if len(selected_rows) > max_keywords:
                    totals["capped_tenants"] += 1
                    selected_rows = selected_rows[:max_keywords]
                keyword_sites = [
                    (int(row[0]), int(row[1]))
                    for row in selected_rows
                ]
                keyword_ids = [row[0] for row in keyword_sites]
                totals["tenants"] += 1
                totals["keywords"] += len(keyword_ids)
                completed_rows = (
                    await session.execute(
                        select(SeoRankSnapshot.keyword_id, SeoRankSnapshot.device).where(
                            SeoRankSnapshot.tenant_id == tenant_id,
                            SeoRankSnapshot.engine == "baidu",
                            SeoRankSnapshot.source == "chinaz_top50",
                            SeoRankSnapshot.checked_at >= day_start_utc,
                            SeoRankSnapshot.keyword_id.in_(keyword_ids),
                        )
                    )
                ).all()
                completed = {(int(row[0]), row[1]) for row in completed_rows}

                for device in ("desktop", "mobile"):
                    pending_rows = [
                        (keyword_id, site_id)
                        for keyword_id, site_id in keyword_sites
                        if (keyword_id, device) not in completed
                    ]
                    totals["skipped_pairs"] += len(keyword_ids) - len(pending_rows)
                    for site_id, pending_ids in _group_keyword_ids_by_site(pending_rows):
                        remaining = max_requests - totals["requests"]
                        for keyword_batch in _limited_batches(
                            pending_ids, batch_size, remaining
                        ):
                            totals["requests"] += len(keyword_batch)
                            try:
                                result = await collect_rank_serp_for_tenant(
                                    session=session,
                                    tenant_id=tenant_id,
                                    site_id=site_id,
                                    keyword_ids=keyword_batch,
                                    devices=[device],
                                    max_keywords=None,
                                    use_ai=settings.seo_rank_scheduler_use_ai,
                                    captured_at=batch_captured_at,
                                )
                            except Exception:  # noqa: BLE001
                                await session.rollback()
                                totals["errors"] += len(keyword_batch)
                                logger.exception(
                                    "[scheduler][SEO] 客户 %s 站点 %s 的 %s 批次采集失败（关键词 %s 个）",
                                    tenant_id,
                                    site_id,
                                    device,
                                    len(keyword_batch),
                                )
                                continue
                            totals["snapshots"] += result["snapshots"]
                            totals["serp_results"] += result["serp_results"]
                            totals["errors"] += len(result["errors"])
        logger.info("[scheduler][SEO] 每日百度前 50 排名采集完成: %s", totals)
    finally:
        release_file_lock(lock_fh)
