"""Background jobs owned exclusively by the independent SEO service."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import TypeVar
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select

from app.config import get_settings, parse_seo_rank_engine_intervals
from app.database import async_session_factory
from app.models.seo import SeoKeywordAsset, SeoMetricSnapshot, SeoRankSnapshot
from app.module_scope import list_active_module_tenants
from app.process_lock import acquire_file_lock, release_file_lock
from app.seo_automation_runs import finish_automation_run, start_automation_run
from app.seo_rank_limits import SEO_RANK_COLLECTION_LOCK_PATH
from app.seo_serp import chinaz_rank_status, dataforseo_status

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_SUPPORTED_SCHEDULED_ENGINES = ("baidu", "sogou", "360", "google", "bing")
_ENGINE_SOURCES = {
    "baidu": {"chinaz_rank", "chinaz_top50"},
    "sogou": {"chinaz_domain_keywords"},
    "360": {"chinaz_rank", "chinaz_domain_keywords"},
    "google": {"dataforseo_live"},
    "bing": {"dataforseo_live"},
}
_SUPPLIER_ACTION_REQUIRED_CODES = {
    "provider_quota_exceeded",
    "provider_ip_rejected",
    "provider_auth_failed",
}


def _scheduled_rank_engines(
    settings: object,
    *,
    dataforseo_configured: bool | None = None,
    chinaz_status: dict[str, dict] | None = None,
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
    if chinaz_status is None:
        # Preserve the historical helper contract for tests/callers that only
        # supplied DataForSEO readiness. The real scheduler always passes the
        # complete device-aware Chinaz status computed above.
        chinaz_status = {"baidu": {"configured": True}}
    return [
        engine
        for engine in requested
        if (
            dataforseo_configured
            if engine in {"google", "bing"}
            else bool(chinaz_status.get(engine, {}).get("configured"))
        )
    ]


def _engine_interval_days(settings: object) -> dict[str, int]:
    return parse_seo_rank_engine_intervals(
        getattr(settings, "seo_rank_scheduler_engine_interval_days", "")
    )


def _collection_due(
    last_success_at: datetime | None,
    interval_days: int,
    now_utc: datetime,
) -> bool:
    """Retry daily after failure; a successful observation starts the cadence."""
    if last_success_at is None:
        return True
    if last_success_at.tzinfo is not None:
        last_success_at = last_success_at.astimezone(timezone.utc).replace(tzinfo=None)
    if now_utc.tzinfo is not None:
        now_utc = now_utc.astimezone(timezone.utc).replace(tzinfo=None)
    return last_success_at <= now_utc - timedelta(days=max(1, interval_days))


async def _latest_successful_collections(
    session,
    *,
    tenant_id: int,
    site_ids: set[int],
    engines: set[str],
) -> dict[tuple[int, str, str], datetime]:
    """Load persistent provider success markers for non-daily engines."""
    latest: dict[tuple[int, str, str], datetime] = {}
    if not site_ids or not engines:
        return latest
    latest_health = (
        select(
            SeoMetricSnapshot.site_id.label("site_id"),
            SeoMetricSnapshot.dimension.label("dimension"),
            func.max(SeoMetricSnapshot.observed_at).label("observed_at"),
        )
        .where(
            SeoMetricSnapshot.tenant_id == tenant_id,
            SeoMetricSnapshot.site_id.in_(site_ids),
            SeoMetricSnapshot.metric_type == "rank_provider_health",
            SeoMetricSnapshot.source == "chinaz",
        )
        .group_by(SeoMetricSnapshot.site_id, SeoMetricSnapshot.dimension)
        .subquery()
    )
    health_rows = (
        await session.execute(
            select(
                SeoMetricSnapshot.site_id,
                SeoMetricSnapshot.dimension,
                SeoMetricSnapshot.status,
                SeoMetricSnapshot.observed_at,
            )
            .join(
                latest_health,
                and_(
                    SeoMetricSnapshot.site_id == latest_health.c.site_id,
                    SeoMetricSnapshot.dimension == latest_health.c.dimension,
                    SeoMetricSnapshot.observed_at == latest_health.c.observed_at,
                ),
            )
            .where(
                SeoMetricSnapshot.tenant_id == tenant_id,
                SeoMetricSnapshot.site_id.in_(site_ids),
                SeoMetricSnapshot.metric_type == "rank_provider_health",
                SeoMetricSnapshot.source == "chinaz",
            )
        )
    ).all()
    for site_id, dimension, status, observed_at in health_rows:
        engine, separator, device = str(dimension).partition(":")
        if (
            status == "available"
            and separator
            and engine in engines
            and device in {"desktop", "mobile"}
        ):
            latest[(int(site_id), engine, device)] = observed_at

    snapshot_engines = engines.intersection({"google", "bing"})
    if not snapshot_engines:
        return latest
    automatic_sources = set().union(
        *(_ENGINE_SOURCES[engine] for engine in snapshot_engines)
    )
    snapshot_rows = (
        await session.execute(
            select(
                SeoRankSnapshot.site_id,
                SeoRankSnapshot.engine,
                SeoRankSnapshot.device,
                func.max(SeoRankSnapshot.checked_at),
            )
            .where(
                SeoRankSnapshot.tenant_id == tenant_id,
                SeoRankSnapshot.site_id.in_(site_ids),
                SeoRankSnapshot.engine.in_(snapshot_engines),
                SeoRankSnapshot.source.in_(automatic_sources),
            )
            .group_by(
                SeoRankSnapshot.site_id,
                SeoRankSnapshot.engine,
                SeoRankSnapshot.device,
            )
        )
    ).all()
    for site_id, engine, device, checked_at in snapshot_rows:
        key = (int(site_id), engine, device)
        if checked_at is not None and (
            key not in latest or checked_at > latest[key]
        ):
            latest[key] = checked_at
    return latest


async def _rollback_tenant_session(session, tenant_id: int) -> None:
    """Contain a broken transaction/connection inside one tenant run."""
    try:
        await session.rollback()
    except Exception:  # noqa: BLE001
        logger.exception(
            "[scheduler][SEO] 客户 %s 的数据库会话回滚失败，已隔离该会话",
            tenant_id,
        )
        try:
            await session.close()
        except Exception:  # noqa: BLE001
            logger.exception(
                "[scheduler][SEO] 客户 %s 的数据库会话关闭失败",
                tenant_id,
            )


@asynccontextmanager
async def _isolated_tenant_session(tenant_id: int):
    """Give each tenant a disposable session and contain connection failures."""
    try:
        async with async_session_factory() as session:
            yield session
    except Exception:  # noqa: BLE001
        logger.exception(
            "[scheduler][SEO] 客户 %s 的数据库会话失败，已跳过且不影响后续客户",
            tenant_id,
        )


def _scheduled_health_summary(
    *,
    incomplete: bool,
    successful_observations: int,
    errors: list[dict],
) -> dict[str, object]:
    """Preserve the first actionable provider error in the final run marker."""
    if not incomplete:
        return {
            "status": "available",
            "text_value": "scheduler_complete",
            "code": None,
            "status_code": None,
            "error_message": None,
        }
    first = next(
        (
            error for error in errors
            if error.get("code") in _SUPPLIER_ACTION_REQUIRED_CODES
        ),
        errors[0] if errors else None,
    ) or {
        "code": "scheduler_budget_exhausted",
        "message": "定时采集预算已用完，将在下一日继续",
    }
    code = str(first.get("code") or "scheduler_incomplete")
    return {
        "status": "partial" if successful_observations > 0 else "failed",
        "text_value": code,
        "code": code,
        "status_code": first.get("status_code"),
        "error_message": str(
            first.get("message") or "定时采集未完成，将在下一日重试"
        ),
    }


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


def _rotate_daily(
    values: list[_T],
    now_utc: datetime,
    *,
    salt: int = 0,
) -> list[_T]:
    """Rotate constrained work daily so fixed ordering cannot starve later items."""
    if len(values) < 2:
        return list(values)
    instant = now_utc
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    local_ordinal = instant.astimezone(_SHANGHAI_TZ).date().toordinal()
    offset = (local_ordinal + salt) % len(values)
    return [*values[offset:], *values[:offset]]


def _local_day_start_utc(now: datetime | None = None) -> datetime:
    """Return Shanghai midnight as naive UTC for the database DateTime fields."""
    local_now = now or datetime.now(_SHANGHAI_TZ)
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_start.astimezone(timezone.utc).replace(tzinfo=None)


async def collect_daily_seo_rankings() -> None:
    """Collect due desktop/mobile rankings within configured per-engine cadence."""
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
    domestic_status = chinaz_rank_status()
    engines = _scheduled_rank_engines(
        settings,
        dataforseo_configured=bool(provider_status["configured"]),
        chinaz_status=domestic_status,
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
    engine_intervals = _engine_interval_days(settings)
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
        async with async_session_factory() as discovery_session:
            entitled_tenant_ids = [
                tenant.id
                for tenant in await list_active_module_tenants(discovery_session, "seo")
            ]
            if not entitled_tenant_ids:
                logger.info("[scheduler][SEO] 没有已开通且有效的 SEO 客户，本次跳过")
                return
            unassigned_rows = (
                await discovery_session.execute(
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
                await discovery_session.scalars(
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
        if max_requests < len(tenant_ids):
            tenant_ids = _rotate_daily(tenant_ids, batch_captured_at)
        per_tenant_request_budget = max(
            1, max_requests // max(1, len(tenant_ids))
        )
        for tenant_id in tenant_ids:
            if totals["requests"] >= max_requests:
                break
            async with _isolated_tenant_session(int(tenant_id)) as session:
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
                site_ids = {row[1] for row in keyword_sites}
                non_daily_engines = {
                    engine for engine in engines
                    if engine_intervals.get(engine, 1) > 1
                }
                latest_success = await _latest_successful_collections(
                    session,
                    tenant_id=int(tenant_id),
                    site_ids=site_ids,
                    engines=non_daily_engines,
                )
                due_pairs = {
                    (site_id, engine, device)
                    for site_id in site_ids
                    for engine in engines
                    for device in ("desktop", "mobile")
                    if _collection_due(
                        latest_success.get((site_id, engine, device)),
                        engine_intervals.get(engine, 1),
                        batch_captured_at,
                    )
                }
                planned_count = sum(
                    (site_id, engine, device) in due_pairs
                    for _keyword_id, site_id in keyword_sites
                    for engine in engines
                    for device in ("desktop", "mobile")
                )
                if planned_count == 0:
                    logger.info(
                        "[scheduler][SEO] 客户 %s 今日无到期排名采集项",
                        tenant_id,
                    )
                    continue
                per_pair_request_budget = max(
                    1, per_tenant_request_budget // len(due_pairs)
                )
                totals["tenants"] += 1
                totals["keywords"] += len(keyword_ids)
                run_id = await start_automation_run(
                    tenant_id=int(tenant_id),
                    job_type="ranking",
                    planned_count=planned_count,
                )
                tenant_success = tenant_failed = tenant_skipped = 0
                tenant_provider_requests = 0
                tenant_errors: list[str] = []
                try:
                    snapshot_scan_start = min(
                        day_start_utc,
                        batch_captured_at - timedelta(
                            days=max(
                                [engine_intervals.get(engine, 1) for engine in engines]
                                or [1]
                            )
                        ),
                    )
                    completed_rows = (
                        await session.execute(
                            select(
                                SeoRankSnapshot.keyword_id,
                                SeoRankSnapshot.engine,
                                SeoRankSnapshot.device,
                                SeoRankSnapshot.source,
                                SeoRankSnapshot.checked_at,
                            ).where(
                                SeoRankSnapshot.tenant_id == tenant_id,
                                SeoRankSnapshot.engine.in_(engines),
                                SeoRankSnapshot.checked_at >= snapshot_scan_start,
                                SeoRankSnapshot.keyword_id.in_(keyword_ids),
                            )
                        )
                    ).all()
                    completed = {
                        (int(row[0]), row[1], row[2])
                        for row in completed_rows
                        if (
                            row[3] in _ENGINE_SOURCES.get(row[1], set())
                            and row[4] >= (
                                day_start_utc
                                if engine_intervals.get(row[1], 1) <= 1
                                else batch_captured_at - timedelta(
                                    days=engine_intervals.get(row[1], 1)
                                )
                            )
                        )
                    }

                    scheduled_units = [
                        (site_id, engine, device)
                        for engine in engines
                        for device in ("desktop", "mobile")
                        for site_id in sorted(site_ids)
                        if (site_id, engine, device) in due_pairs
                    ]
                    if per_tenant_request_budget < planned_count:
                        scheduled_units = _rotate_daily(
                            scheduled_units,
                            batch_captured_at,
                            salt=int(tenant_id),
                        )
                    for site_id, engine, device in scheduled_units:
                        eligible_ids = [
                            keyword_id
                            for keyword_id, keyword_site_id in keyword_sites
                            if keyword_site_id == site_id
                        ]
                        pending_ids = [
                            keyword_id
                            for keyword_id in eligible_ids
                            if (keyword_id, engine, device) not in completed
                        ]
                        already_completed = len(eligible_ids) - len(pending_ids)
                        totals["skipped_pairs"] += already_completed
                        tenant_skipped += already_completed
                        if per_pair_request_budget < len(pending_ids):
                            pending_ids = _rotate_daily(
                                pending_ids,
                                batch_captured_at,
                                salt=(
                                    int(tenant_id)
                                    + site_id
                                    + engines.index(engine)
                                    + (1 if device == "mobile" else 0)
                                ),
                            )
                        attempted = 0
                        pair_provider_requests = 0
                        site_attempted = 0
                        site_incomplete = False
                        site_successful_observations = 0
                        site_errors: list[dict] = []
                        for candidate_batch in _chunks(pending_ids, batch_size):
                            remaining = min(
                                max_requests - totals["requests"],
                                per_tenant_request_budget - tenant_provider_requests,
                                per_pair_request_budget - pair_provider_requests,
                            )
                            if engine in {"google", "bing"}:
                                remaining = min(
                                    remaining,
                                    max_dataforseo_requests
                                    - totals["dataforseo_requests"],
                                )
                            if remaining <= 0:
                                site_incomplete = True
                                break
                            keyword_batch = candidate_batch[:remaining]
                            attempted += len(keyword_batch)
                            site_attempted += len(keyword_batch)
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
                                    provider_request_budget=remaining,
                                )
                            except Exception as exc:  # noqa: BLE001
                                await _rollback_tenant_session(session, int(tenant_id))
                                # The collector can fail after the provider has already
                                # accepted requests but before it returns exact usage.
                                # Conservatively reserve the full allowance passed to
                                # this batch so later work can never exceed a hard cap.
                                totals["requests"] += remaining
                                tenant_provider_requests += remaining
                                pair_provider_requests += remaining
                                if engine in {"google", "bing"}:
                                    totals["dataforseo_requests"] += remaining
                                totals["errors"] += len(keyword_batch)
                                tenant_failed += len(keyword_batch)
                                site_incomplete = True
                                site_errors.append({
                                    "code": "scheduler_batch_error",
                                    "message": "定时采集批次执行失败，将在下一日重试",
                                })
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
                            reported_requests = result.get("provider_requests")
                            if reported_requests is None:
                                reported_requests = result.get(
                                    "requests", len(keyword_batch)
                                )
                            provider_requests = max(0, int(reported_requests))
                            totals["requests"] += provider_requests
                            tenant_provider_requests += provider_requests
                            pair_provider_requests += provider_requests
                            if engine in {"google", "bing"}:
                                totals["dataforseo_requests"] += provider_requests
                            skipped_errors = sum(
                                item.get("code") in {
                                    "keyword_not_found",
                                    "provider_budget_exhausted",
                                }
                                for item in result["errors"]
                            )
                            result_errors = len(result["errors"]) - skipped_errors
                            keyword_fallbacks = sum(
                                item.get("code") == "keyword_not_found"
                                for item in result["errors"]
                            )
                            site_successful_observations += (
                                len(keyword_batch)
                                - len(result["errors"])
                                + keyword_fallbacks
                            )
                            hard_errors = [
                                item for item in result["errors"]
                                if item.get("code") != "keyword_not_found"
                            ]
                            if hard_errors:
                                site_incomplete = True
                                site_errors.extend(hard_errors)
                            tenant_failed += result_errors
                            tenant_skipped += skipped_errors
                            tenant_success += max(
                                0,
                                len(keyword_batch)
                                - result_errors
                                - skipped_errors,
                            )
                            tenant_errors.extend(
                                f"{engine}/{device}:{item.get('code', 'provider_error')}"
                                for item in result["errors"][:5]
                            )
                            totals["snapshots"] += result["snapshots"]
                            totals["serp_results"] += result["serp_results"]
                            totals["errors"] += result_errors
                            totals["skipped_pairs"] += skipped_errors
                        if site_attempted < len(pending_ids):
                            site_incomplete = True
                        if (
                            engine in {"baidu", "sogou", "360"}
                            and engine_intervals.get(engine, 1) > 1
                            and pending_ids
                        ):
                            health = _scheduled_health_summary(
                                incomplete=site_incomplete,
                                successful_observations=site_successful_observations,
                                errors=site_errors,
                            )
                            session.add(SeoMetricSnapshot(
                                tenant_id=tenant_id,
                                site_id=site_id,
                                metric_type="rank_provider_health",
                                dimension=f"{engine}:{device}",
                                text_value=str(health["text_value"]),
                                source="chinaz",
                                data_quality="verified",
                                status=str(health["status"]),
                                error_message=health["error_message"],
                                raw_payload={
                                    "scheduler_summary": True,
                                    "code": health["code"],
                                    "status_code": health["status_code"],
                                    "attempted_keywords": site_attempted,
                                    "planned_keywords": len(pending_ids),
                                    "provider_requests": pair_provider_requests,
                                },
                                observed_at=datetime.utcnow(),
                            ))
                            await session.commit()
                        budget_skipped = len(pending_ids) - attempted
                        tenant_skipped += budget_skipped
                        totals["skipped_pairs"] += budget_skipped
                except Exception as exc:  # noqa: BLE001
                    await _rollback_tenant_session(session, int(tenant_id))
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
