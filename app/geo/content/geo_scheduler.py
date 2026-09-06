"""GEO-only APScheduler: visibility patrol + nightly daily metrics.

Started by both `app.main` and `app.geo_main`. A cross-process file lock
prevents double-fire when both processes are up (Windows uses msvcrt).
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

try:
    import fcntl
except ModuleNotFoundError:
    fcntl = None

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
_lock_fh = None
_status = "stopped"


def scheduler_status() -> str:
    return _status


async def run_geo_daily_metrics_nightly() -> None:
    from app.geo.content.daily_metrics import nightly_rebuild_recent_tenants

    try:
        summary = await nightly_rebuild_recent_tenants(lookback_days=2)
        logger.info("[geo-scheduler] daily metrics nightly %s", summary)
    except Exception:  # noqa: BLE001
        logger.exception("[geo-scheduler] daily metrics nightly failed")


async def run_geo_visibility_patrols() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from sqlalchemy import select

    from app.config import get_settings
    from app.database import async_session_factory
    from app.geo.content.patrol import (
        count_patrol_runs_today,
        execute_patrol_run_owned,
        should_run_scheduled_patrol,
    )
    from app.models import GeoVisibilityPatrolRun, GeoVisibilityPatrolSettings, Tenant

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    day_limit = int(getattr(get_settings(), "geo_patrol_max_runs_per_day", 24) or 24)
    day_limit = max(1, min(day_limit, 500))
    async with async_session_factory() as session:
        rows = list(
            await session.scalars(
                select(GeoVisibilityPatrolSettings).where(
                    GeoVisibilityPatrolSettings.enabled.is_(True),
                )
            )
        )
        for st in rows:
            start_h = int(st.window_start_hour if st.window_start_hour is not None else st.daily_hour if st.daily_hour is not None else 6)
            end_h = int(st.window_end_hour if st.window_end_hour is not None else st.daily_hour if st.daily_hour is not None else 22)
            interval = int(getattr(st, "interval_hours", None) or 24)
            last_at = getattr(st, "last_scheduled_at", None)
            if not should_run_scheduled_patrol(
                now=now,
                window_start_hour=start_h,
                window_end_hour=end_h,
                interval_hours=interval,
                last_scheduled_at=last_at,
            ):
                continue
            await session.execute(select(Tenant.id).where(Tenant.id == st.tenant_id).with_for_update())
            from app.geo.retest import reserved_week
            if await reserved_week(session, st.tenant_id):
                await session.commit()
                continue
            used = await count_patrol_runs_today(session, st.tenant_id)
            if used >= day_limit:
                logger.warning(
                    "[geo-scheduler] skip patrol tenant=%s daily quota %s/%s",
                    st.tenant_id,
                    used,
                    day_limit,
                )
                await session.commit()
                continue
            inflight = await session.scalar(
                select(GeoVisibilityPatrolRun.id)
                .where(
                    GeoVisibilityPatrolRun.tenant_id == st.tenant_id,
                    GeoVisibilityPatrolRun.status.in_(("pending", "running")),
                )
                .limit(1)
            )
            if inflight:
                logger.info(
                    "[geo-scheduler] skip patrol tenant=%s already inflight run=%s",
                    st.tenant_id,
                    inflight,
                )
                await session.commit()
                continue
            run = GeoVisibilityPatrolRun(
                tenant_id=st.tenant_id,
                status="pending",
                trigger="schedule",
                auto_persist=bool(st.auto_persist),
                prefer_real=bool(st.prefer_real),
                prompt_limit=int(st.prompt_limit or 20),
                engine_keys=st.engine_keys,
                created_by=None,
            )
            session.add(run)
            st.last_scheduled_at = datetime.utcnow()
            await session.commit()
            await session.refresh(run)
            rid = run.id
            try:
                await execute_patrol_run_owned(session, rid)
                logger.info(
                    "[geo-scheduler] patrol done tenant=%s run=%s window=%s-%s interval=%sh",
                    st.tenant_id,
                    rid,
                    start_h,
                    end_h,
                    interval,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[geo-scheduler] patrol failed tenant=%s run=%s",
                    st.tenant_id,
                    rid,
                )


async def run_geo_stale_reconciliation() -> None:
    """Persist stale task recovery independently from all GET requests."""
    from app.geo.content.async_jobs import reconcile_stale_jobs_background
    from app.geo.content.patrol import reconcile_stale_patrol_runs_background

    try:
        jobs = await reconcile_stale_jobs_background()
        patrols = await reconcile_stale_patrol_runs_background()
        if any(jobs.values()) or any(patrols.values()):
            logger.info(
                "[geo-scheduler] stale reconciliation jobs=%s patrols=%s",
                jobs,
                patrols,
            )
    except Exception:  # noqa: BLE001
        logger.exception("[geo-scheduler] stale reconciliation failed")


def _lock_path() -> Path:
    return Path(tempfile.gettempdir()) / "ai_sni_geo_scheduler.lock"


def _acquire_lock() -> bool:
    global _lock_fh
    path = _lock_path()
    fh = open(path, "a+b")
    try:
        fh.seek(0)
        if fh.read(1) == b"":
            fh.write(b"0")
            fh.flush()
        fh.seek(0)
        if fcntl is not None:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            import msvcrt

            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        _lock_fh = fh
        return True
    except OSError:
        fh.close()
        return False


def _release_lock() -> None:
    global _lock_fh
    if _lock_fh is None:
        return
    try:
        if fcntl is not None:
            fcntl.flock(_lock_fh, fcntl.LOCK_UN)
        else:
            import msvcrt

            _lock_fh.seek(0)
            msvcrt.locking(_lock_fh.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    try:
        _lock_fh.close()
    finally:
        _lock_fh = None


def start_geo_scheduler() -> bool:
    """Register patrol + nightly metrics. Returns False if another process holds the lock."""
    global _status
    if scheduler.running:
        _status = "running"
        return True
    if not _acquire_lock():
        _status = "skipped"
        logger.info("[geo-scheduler] lock held elsewhere, this process will not tick")
        return False
    scheduler.add_job(
        run_geo_visibility_patrols,
        CronTrigger(minute=5),
        id="geo_visibility_patrols",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_geo_daily_metrics_nightly,
        CronTrigger(hour=0, minute=40),
        id="geo_daily_metrics_nightly",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _status = "running"
    jobs = scheduler.get_jobs()
    nxt = str(jobs[0].next_run_time) if jobs else None
    logger.info("[geo-scheduler] started, next=%s", nxt)
    return True


def shutdown_geo_scheduler() -> None:
    global _status
    if scheduler.running:
        scheduler.shutdown(wait=False)
    _release_lock()
    _status = "stopped"
