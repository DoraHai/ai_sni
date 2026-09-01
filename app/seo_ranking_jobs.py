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
from app.seo_automation_runs import finish_automation_run, start_automation_run
from app.seo_rank_limits import SEO_RANK_COLLECTION_LOCK_PATH
from app.seo_serp import dataforseo_status

logger = logging.getLogger(__name__)

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_SUPPORTED_SCHEDULED_ENGINES = ("baidu", "google", "bing")
_ENGINE_SOURCES = {
    "baidu": "chinaz_top50",
    "google": "dataforseo_live",
    "bing": "dataforseo_live",
}


def _scheduled_rank_engines(
    settings: object,
    *,
    dataforseo_configured: bool | None = None,
) -> list[str]:
    """Return ordered, supported engines whose provider is ready to run."""
    raw = str(getattr(settings, "seo_rank_scheduler_engines", "baidu"))
    requested = list(
        dict.fromkeys(
            item.strip().lower()
            for item in raw.split(",")
            if item.strip().lower() in _SUPPORTED_SCHEDULED_ENGINES
        )
    )
    if dataforseo_configured is None:
        dataforseo_configured = bool(dataforseo_status()["configured"])
    return [
        engine
        for engine in requested
        if engine == "baidu" or dataforseo_configured
    ]


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
    """Collect configured daily desktop/mobile rankings within hard limits."""
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
    max_dataforseo_requests = max(
        1,
        getattr(settings, "seo_dataforseo_scheduler_max_requests_per_run", 200),
    )
    batch_size = max(1, settings.seo_rank_scheduler_batch_size)
    provider_status = dataforseo_status()
    engines = _scheduled_rank_engines(
        settings,
        dataforseo_configured=bool(provider_status["configured"]),
    )
    requested_engines = str(
        getattr(settings, "seo_rank_scheduler_engines", "baidu")
    ).lower()
    if not provider_status["configured"] and any(
        engine in requested_engines for engine in ("google", "bing")
    ):
        logger.info(
            "[scheduler][SEO] DataForSEO 未配置，Google/Bing 自动排名已安全跳过"
        )
    if not engines:
        logger.info("[scheduler][SEO] 没有已配置且可用的自动排名引擎，本次跳过")
        release_file_lock(lock_fh)
        return
    batch_captured_at = datetime.utcnow()
    day_start_utc = _local_day_start_utc()
    totals = {
        "tenants": 0,
        "keywords": 0,
        "requests": 0,
        "dataforseo_requests": 0,
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
                planned_count = len(keyword_ids) * 2 * len(engines)
                run_id = await start_automation_run(
                    tenant_id=int(tenant_id),
                    job_type="ranking",
                    planned_count=planned_count,
                )
                tenant_success = tenant_failed = tenant_skipped = 0
                tenant_errors: list[str] = []
                try:
                    completed_rows = (
                        await session.execute(
                            select(
                                SeoRankSnapshot.keyword_id,
                                SeoRankSnapshot.engine,
                                SeoRankSnapshot.device,
                                SeoRankSnapshot.source,
                            ).where(
                                SeoRankSnapshot.tenant_id == tenant_id,
                                SeoRankSnapshot.engine.in_(engines),
                                SeoRankSnapshot.checked_at >= day_start_utc,
                                SeoRankSnapshot.keyword_id.in_(keyword_ids),
                            )
                        )
                    ).all()
                    completed = {
                        (int(row[0]), row[1], row[2])
                        for row in completed_rows
                        if row[3] == _ENGINE_SOURCES.get(row[1])
                    }

                    for engine in engines:
                        for device in ("desktop", "mobile"):
                            pending_rows = [
                                (keyword_id, site_id)
                                for keyword_id, site_id in keyword_sites
                                if (keyword_id, engine, device) not in completed
                            ]
                            already_completed = len(keyword_ids) - len(pending_rows)
                            totals["skipped_pairs"] += already_completed
                            tenant_skipped += already_completed
                            attempted = 0
                            for site_id, pending_ids in _group_keyword_ids_by_site(pending_rows):
                                remaining = max_requests - totals["requests"]
                                if engine in {"google", "bing"}:
                                    remaining = min(
                                        remaining,
                                        max_dataforseo_requests
                                        - totals["dataforseo_requests"],
                                    )
                                for keyword_batch in _limited_batches(
                                    pending_ids, batch_size, remaining
                                ):
                                    attempted += len(keyword_batch)
                                    totals["requests"] += len(keyword_batch)
                                    if engine in {"google", "bing"}:
                                        totals["dataforseo_requests"] += len(keyword_batch)
                                    try:
                                        result = await collect_rank_serp_for_tenant(
                                            session=session,
                                            tenant_id=tenant_id,
                                            site_id=site_id,
                                            keyword_ids=keyword_batch,
                                            devices=[device],
                                            max_keywords=None,
                                            engine=engine,
                                            use_ai=settings.seo_rank_scheduler_use_ai,
                                            captured_at=batch_captured_at,
                                        )
                                    except Exception as exc:  # noqa: BLE001
                                        await session.rollback()
                                        totals["errors"] += len(keyword_batch)
                                        tenant_failed += len(keyword_batch)
                                        tenant_errors.append(
                                            f"{engine}/{device}:{type(exc).__name__}"
                                        )
                                        logger.exception(
                                            "[scheduler][SEO] 客户 %s 站点 %s 的 %s/%s 批次采集失败（关键词 %s 个）",
                                            tenant_id,
                                            site_id,
                                            engine,
                                            device,
                                            len(keyword_batch),
                                        )
                                        continue
                                    result_errors = len(result["errors"])
                                    tenant_failed += result_errors
                                    tenant_success += max(
                                        0, len(keyword_batch) - result_errors
                                    )
                                    tenant_errors.extend(
                                        f"{engine}/{device}:{item.get('code', 'provider_error')}"
                                        for item in result["errors"][:5]
                                    )
                                    totals["snapshots"] += result["snapshots"]
                                    totals["serp_results"] += result["serp_results"]
                                    totals["errors"] += result_errors
                            budget_skipped = len(pending_rows) - attempted
                            tenant_skipped += budget_skipped
                            totals["skipped_pairs"] += budget_skipped
                except Exception as exc:  # noqa: BLE001
                    await session.rollback()
                    remaining_pairs = max(
                        0,
                        planned_count
                        - tenant_success
                        - tenant_failed
                        - tenant_skipped,
                    )
                    tenant_failed += remaining_pairs
                    totals["errors"] += remaining_pairs
                    tenant_errors.append(f"run:{type(exc).__name__}")
                    logger.exception(
                        "[scheduler][SEO] 客户 %s 的排名自动化运行失败",
                        tenant_id,
                    )
                finally:
                    await finish_automation_run(
                        run_id,
                        planned_count=planned_count,
                        success_count=tenant_success,
                        failed_count=tenant_failed,
                        skipped_count=tenant_skipped,
                        error_summary="; ".join(tenant_errors[:10]),
                    )
        logger.info(
            "[scheduler][SEO] 每日多引擎自然排名采集完成 engines=%s totals=%s",
            engines,
            totals,
        )
    finally:
        release_file_lock(lock_fh)
