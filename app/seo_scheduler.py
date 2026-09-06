"""Scheduler owned exclusively by the independent SEO service."""

import logging
import tempfile
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from app.seo_qa_batches import run_qa_batches
from app.seo_backlinks import discover_published_backlinks
from app.seo_image_verification import verify_pending_images
from app.seo_cockpit_metrics import collect_cockpit_metrics

from app.config import get_settings
from app.process_lock import acquire_file_lock, release_file_lock
from app.seo_ranking_jobs import collect_daily_seo_rankings
from app.seo_ai_operations import reconcile_seo_ai_operations
from app.seo_snapshot_retention import prune_old_single_page_snapshots
from app.seo_monitoring_jobs import (
    collect_scheduled_competitors,
    fail_stale_crawl_runs,
    verify_scheduled_backlinks,
    verify_scheduled_qa,
)

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
    settings = get_settings()
    rank_hour = int(settings.seo_rank_scheduler_hour)
    rank_minute = int(settings.seo_rank_scheduler_minute)
    seo_scheduler.add_job(
        collect_daily_seo_rankings,
        CronTrigger(hour=rank_hour, minute=rank_minute),
        id="collect_daily_seo_rankings",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    seo_scheduler.add_job(
        collect_scheduled_competitors,
        CronTrigger(hour=3, minute=0),
        id="collect_scheduled_seo_competitors",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    seo_scheduler.add_job(
        verify_scheduled_qa,
        IntervalTrigger(hours=1),
        id="verify_scheduled_seo_qa",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    seo_scheduler.add_job(
        discover_published_backlinks,
        IntervalTrigger(hours=1),
        id="discover_published_seo_backlinks",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    seo_scheduler.add_job(
        verify_scheduled_backlinks,
        CronTrigger(hour=4, minute=0),
        id="verify_scheduled_seo_backlinks",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    seo_scheduler.add_job(
        fail_stale_crawl_runs,
        IntervalTrigger(minutes=15),
        id="fail_stale_seo_crawl_runs",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=900,
    )
    seo_scheduler.add_job(
        prune_old_single_page_snapshots,
        CronTrigger(hour=5, minute=0),
        id="prune_old_seo_single_page_snapshots",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    seo_scheduler.add_job(
        reconcile_seo_ai_operations,
        IntervalTrigger(minutes=1),
        id="reconcile_seo_ai_operations",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )
    seo_scheduler.add_job(verify_pending_images,IntervalTrigger(minutes=1),id='verify_seo_images',replace_existing=True,max_instances=1,coalesce=True,misfire_grace_time=60)
    seo_scheduler.add_job(collect_cockpit_metrics,IntervalTrigger(hours=1),id='collect_seo_cockpit_metrics',replace_existing=True,max_instances=1,coalesce=True,misfire_grace_time=3600)
    seo_scheduler.add_job(run_qa_batches,IntervalTrigger(seconds=10),id='run_seo_qa_batches',replace_existing=True,max_instances=1,coalesce=True,misfire_grace_time=60)
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
