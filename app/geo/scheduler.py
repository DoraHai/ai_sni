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
from app.models import GeoVisibilityPatrolRun, GeoVisibilityPatrolSettings

logger = logging.getLogger(__name__)

geo_scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
_LOCK_PATH = "/tmp/geo_scheduler.lock"
_lock_file: IO[str] | None = None
_windows_lock = ThreadLock()


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
        settings_rows = list(
            await session.scalars(
                select(GeoVisibilityPatrolSettings).where(
                    GeoVisibilityPatrolSettings.enabled.is_(True)
                )
            )
        )
        for patrol_settings in settings_rows:
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

            used = await count_patrol_runs_today(session, patrol_settings.tenant_id)
            if used >= day_limit:
                logger.warning(
                    "[geo-scheduler] tenant=%s reached daily quota %s/%s",
                    patrol_settings.tenant_id,
                    used,
                    day_limit,
                )
                continue

            inflight = await session.scalar(
                select(GeoVisibilityPatrolRun.id)
                .where(
                    GeoVisibilityPatrolRun.tenant_id == patrol_settings.tenant_id,
                    GeoVisibilityPatrolRun.trigger == "schedule",
                    GeoVisibilityPatrolRun.status.in_(("pending", "running")),
                )
                .limit(1)
            )
            if inflight:
                continue

            run = GeoVisibilityPatrolRun(
                tenant_id=patrol_settings.tenant_id,
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
                await execute_patrol_run_owned(session, run.id)
                logger.info(
                    "[geo-scheduler] patrol completed tenant=%s run=%s",
                    patrol_settings.tenant_id,
                    run.id,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[geo-scheduler] patrol failed tenant=%s run=%s",
                    patrol_settings.tenant_id,
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


def start_geo_followup_scheduler() -> bool:
    """Only the independent GEO process starts followups, using its own file lock.

    The shared content scheduler may be owned by the main service. Do not depend
    on that process adopting a GEO-only release, or start a second patrol job.
    """
    if geo_scheduler.running:
        return True
    if not _acquire_scheduler_lock():
        return False
    try:
        from app.geo.publication_monitor import run_monitor_batch
        from app.geo.outcome_review import run_outcome_reviews
        now = datetime.now(ZoneInfo('Asia/Shanghai'))
        geo_scheduler.add_job(run_monitor_batch, CronTrigger(minute='*/10', timezone=ZoneInfo('Asia/Shanghai')),
                              id='geo_publication_monitor', replace_existing=True, max_instances=1, coalesce=True,
                              next_run_time=now)
        geo_scheduler.add_job(run_outcome_reviews, CronTrigger(minute=15, timezone=ZoneInfo('Asia/Shanghai')),
                              id='geo_outcome_reviews', replace_existing=True, max_instances=1, coalesce=True,
                              next_run_time=now)
        geo_scheduler.start()
    except Exception:
        _release_scheduler_lock()
        raise
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
