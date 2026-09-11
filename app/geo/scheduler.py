"""Background jobs owned by the independently deployed GEO service."""

from __future__ import annotations

import logging
from datetime import datetime
from threading import Lock as ThreadLock
from typing import IO
from zoneinfo import ZoneInfo

try:
    import fcntl
except ModuleNotFoundError:  # pragma: no cover - Windows development only
    fcntl = None

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.config import get_settings
from app.database import async_session_factory
from app.geo.content.daily_metrics import nightly_rebuild_recent_tenants
from app.geo.content.patrol import (
    count_patrol_runs_today,
    execute_patrol_run_owned,
    should_run_scheduled_patrol,
)
from app.geo.scheduler_observability import SchedulerTelemetry
from app.models import GeoVisibilityPatrolRun, GeoVisibilityPatrolSettings

logger = logging.getLogger(__name__)

geo_scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
_LOCK_PATH = "/tmp/geo_scheduler.lock"
_lock_file: IO[str] | None = None
_windows_lock = ThreadLock()
_followup_telemetry = SchedulerTelemetry("geo_followup_scheduler")


def followup_scheduler_runtime_status() -> dict:
    """Structured current-process status for publishing follow-up jobs."""
    return _followup_telemetry.snapshot(geo_scheduler)


def record_followup_failure(job_id: str, error: BaseException) -> None:
    """Record an item-level failure caught by a resilient batch runner."""
    _followup_telemetry.record_failure(job_id, error)


async def _run_followup_job(job_id: str, runner) -> None:
    try:
        await runner()
    except Exception as exc:
        _followup_telemetry.record_failure(job_id, exc)
        raise


def _acquire_scheduler_lock() -> bool:
    """Allow only one GEO worker to own scheduled work."""
    global _lock_file
    if fcntl is None:
        return _windows_lock.acquire(blocking=False)
    handle = open(_LOCK_PATH, "w", encoding="utf-8")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False
    _lock_file = handle
    return True


def _release_scheduler_lock() -> None:
    global _lock_file
    if fcntl is None:
        if _windows_lock.locked():
            _windows_lock.release()
        return
    if _lock_file is None:
        return
    try:
        fcntl.flock(_lock_file, fcntl.LOCK_UN)
    finally:
        _lock_file.close()
        _lock_file = None


async def run_geo_daily_metrics_nightly() -> None:
    """Rebuild recent tenant/business/unit daily metrics."""
    try:
        summary = await nightly_rebuild_recent_tenants(lookback_days=2)
        logger.info("[geo-scheduler] daily metrics rebuilt: %s", summary)
    except Exception:  # noqa: BLE001
        logger.exception("[geo-scheduler] daily metrics rebuild failed")


async def run_geo_visibility_patrols() -> None:
    """Start due visibility patrols inside their configured time windows."""
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    day_limit = int(getattr(get_settings(), "geo_patrol_max_runs_per_day", 24) or 24)
    day_limit = max(1, min(day_limit, 500))

    async with async_session_factory() as session:
        from app.geo.content.geo_scheduler import (
            current_patrol_settings,
            scheduled_patrol_settings_query,
        )
        from app.geo.tenant_scope import GeoEntitlementUnavailable, ensure_geo_entitlement

        settings_rows = list(await session.scalars(scheduled_patrol_settings_query()))
        tenant_ids = [int(row.tenant_id) for row in settings_rows]
        for tenant_id in tenant_ids:
            try:
                await ensure_geo_entitlement(session, tenant_id)
            except GeoEntitlementUnavailable:
                continue
            patrol_settings = await current_patrol_settings(session, tenant_id)
            if patrol_settings is None or not bool(patrol_settings.enabled):
                continue
            start_hour = int(
                getattr(patrol_settings, "window_start_hour", None)
                or patrol_settings.daily_hour
                or 6
            )
            end_hour = int(
                getattr(patrol_settings, "window_end_hour", None)
                or patrol_settings.daily_hour
                or 22
            )
            interval_hours = int(
                getattr(patrol_settings, "interval_hours", None) or 24
            )
            if not should_run_scheduled_patrol(
                now=now,
                window_start_hour=start_hour,
                window_end_hour=end_hour,
                interval_hours=interval_hours,
                last_scheduled_at=getattr(patrol_settings, "last_scheduled_at", None),
            ):
                continue

            used = await count_patrol_runs_today(session, tenant_id)
            if used >= day_limit:
                logger.warning(
                    "[geo-scheduler] tenant=%s reached daily quota %s/%s",
                    tenant_id,
                    used,
                    day_limit,
                )
                continue

            inflight = await session.scalar(
                select(GeoVisibilityPatrolRun.id)
                .where(
                    GeoVisibilityPatrolRun.tenant_id == tenant_id,
                    GeoVisibilityPatrolRun.trigger == "schedule",
                    GeoVisibilityPatrolRun.status.in_(("pending", "running")),
                )
                .limit(1)
            )
            if inflight:
                continue

            run = GeoVisibilityPatrolRun(
                tenant_id=tenant_id,
                status="pending",
                trigger="schedule",
                auto_persist=bool(patrol_settings.auto_persist),
                prefer_real=bool(patrol_settings.prefer_real),
                prompt_limit=int(patrol_settings.prompt_limit or 20),
                engine_keys=patrol_settings.engine_keys,
                created_by=None,
            )
            session.add(run)
            patrol_settings.last_scheduled_at = datetime.now()
            await session.commit()
            await session.refresh(run)
            try:
                await execute_patrol_run_owned(session, run.id, tenant_id)
                logger.info(
                    "[geo-scheduler] patrol completed tenant=%s run=%s",
                    tenant_id,
                    run.id,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[geo-scheduler] patrol failed tenant=%s run=%s",
                    tenant_id,
                    run.id,
                )


def start_geo_scheduler() -> None:
    """Start GEO-only jobs in one worker of the GEO service."""
    if geo_scheduler.running:
        return
    if not _acquire_scheduler_lock():
        logger.info("[geo-scheduler] another GEO worker owns the scheduler lock")
        return
    geo_scheduler.add_job(
        run_geo_visibility_patrols,
        CronTrigger(minute=5),
        id="geo_visibility_patrols",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    geo_scheduler.add_job(
        run_geo_daily_metrics_nightly,
        CronTrigger(hour=0, minute=40),
        id="geo_daily_metrics_nightly",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    geo_scheduler.start()
    logger.info("[geo-scheduler] started")


def shutdown_geo_scheduler() -> None:
    """Stop GEO jobs without touching the SEM scheduler process."""
    if geo_scheduler.running:
        geo_scheduler.shutdown(wait=False)
    _release_scheduler_lock()
    _followup_telemetry.set_state("stopped", "none")


def start_geo_followup_scheduler() -> bool:
    """Only the independent GEO process starts followups, using its own file lock.

    The shared content scheduler may be owned by the main service. Do not depend
    on that process adopting a GEO-only release, or start a second patrol job.
    """
    if geo_scheduler.running:
        _followup_telemetry.set_state("active", "current_process")
        return True
    if not _acquire_scheduler_lock():
        _followup_telemetry.set_state("standby", "another_process")
        return False
    try:
        from app.geo.publication_monitor import run_monitor_batch
        from app.geo.outcome_review import run_outcome_reviews
        now = datetime.now(ZoneInfo('Asia/Shanghai'))
        _followup_telemetry.attach(geo_scheduler)

        async def publication_monitor_job():
            await _run_followup_job('geo_publication_monitor', run_monitor_batch)

        async def outcome_reviews_job():
            await _run_followup_job('geo_outcome_reviews', run_outcome_reviews)

        geo_scheduler.add_job(publication_monitor_job, CronTrigger(minute='*/10', timezone=ZoneInfo('Asia/Shanghai')),
                              id='geo_publication_monitor', replace_existing=True, max_instances=1, coalesce=True,
                              next_run_time=now)
        geo_scheduler.add_job(outcome_reviews_job, CronTrigger(minute=15, timezone=ZoneInfo('Asia/Shanghai')),
                              id='geo_outcome_reviews', replace_existing=True, max_instances=1, coalesce=True,
                              next_run_time=now)
        geo_scheduler.start()
    except Exception as exc:
        _followup_telemetry.record_failure('scheduler_startup', exc)
        _followup_telemetry.set_state("stopped", "none")
        _release_scheduler_lock()
        raise
    _followup_telemetry.set_state("active", "current_process")
    logger.info('[geo-followup-scheduler] started publication monitoring and outcome reviews')
    return True


async def supervise_geo_followups():
    """Standby workers retry ownership; OS locks release when the owner exits."""
    import asyncio
    while True:
        try:
            start_geo_followup_scheduler()
        except Exception:
            logger.exception('[geo-followup-scheduler] startup failed, will retry')
        await asyncio.sleep(30)
