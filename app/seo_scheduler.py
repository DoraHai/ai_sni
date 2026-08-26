"""Scheduler owned exclusively by the independent SEO service."""

import logging
import tempfile
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.process_lock import acquire_file_lock, release_file_lock
from app.seo_ranking_jobs import collect_daily_seo_rankings

logger = logging.getLogger(__name__)

seo_scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
_SEO_SCHEDULER_LOCK_PATH = Path(tempfile.gettempdir()) / "seo_scheduler.lock"
_lock_fh = None


def _acquire_scheduler_lock() -> bool:
    global _lock_fh
    _lock_fh = acquire_file_lock(_SEO_SCHEDULER_LOCK_PATH)
    return _lock_fh is not None


def _release_scheduler_lock() -> None:
    global _lock_fh
    release_file_lock(_lock_fh)
    _lock_fh = None


def _start_seo_scheduler() -> None:
    if not _acquire_scheduler_lock():
        logger.info("[scheduler][SEO] 未抢到调度锁，本 worker 不启动 SEO 调度")
        return
    seo_scheduler.add_job(
        collect_daily_seo_rankings,
        CronTrigger(hour=2, minute=0),
        id="collect_daily_seo_rankings",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    seo_scheduler.start()
    logger.info("[scheduler][SEO] 独立调度器已启动")


def start_seo_scheduler() -> None:
    try:
        _start_seo_scheduler()
    except Exception:
        _release_scheduler_lock()
        raise


def shutdown_seo_scheduler() -> None:
    try:
        if seo_scheduler.running:
            seo_scheduler.shutdown(wait=False)
    finally:
        _release_scheduler_lock()
