"""APScheduler 定时任务。

任务清单：
  - fetch_today_keyword_report：每 15 分钟（Asia/Shanghai）
    拉取当天累计报告，并刷新计划/单元/关键词/出价策略
  - fetch_yesterday_keyword_report：每天 02:00（Asia/Shanghai）
    报告同步 → 关键词维度同步（getWord）→ 5 类分级重算 → 规则引擎

在 main.py 的 startup 事件里调 start_scheduler()。
"""
import logging
from asyncio import Lock
from datetime import datetime, timedelta
from threading import Lock as ThreadLock
from zoneinfo import ZoneInfo

try:
    import fcntl
except ModuleNotFoundError:  # Windows has no POSIX file-lock module.
    fcntl = None

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.baidu.sync import (
    sync_adgroups_for_account,
    sync_campaigns_for_account,
    sync_keyword_dimension_reports_for_account,
    sync_keyword_report_for_account,
    sync_keyword_report_for_all_active_accounts,
    sync_keywords_for_account,
    sync_ocpc_packages_for_account,
    sync_operation_records_for_account,
    sync_price_strategies_for_account,
)
from app.classification import reclassify_keywords
from app.database import async_session_factory
from app.models import BaiduAccount, Tenant
from app.rules import run_rules_for_all_tenants
from app.suggestions import run_suggestions_for_all_tenants

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
_report_sync_lock = Lock()
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

# 多 worker 防双跑：uvicorn --workers 2 时每个 worker 都会执行 startup → 各起一个
# APScheduler，导致每日任务跑两次（重复调百度 + 重复写）。用文件排他锁，只让抢到锁的
# 那个 worker 启动调度，其余 worker 跳过。锁随进程退出自动释放。
_SCHEDULER_LOCK_PATH = "/tmp/sem_scheduler.lock"
_lock_fh = None
_windows_scheduler_lock = ThreadLock()
_windows_tenant_sync_locks: dict[int, ThreadLock] = {}


def _acquire_tenant_sync_lock(tenant_id: int):
    if fcntl is None:
        lock = _windows_tenant_sync_locks.setdefault(tenant_id, ThreadLock())
        return lock if lock.acquire(blocking=False) else None
    """跨 worker 的客户级非阻塞锁，避免定时任务和人工刷新重复调用百度。"""
    fh = open(f"/tmp/sem_tenant_sync_{tenant_id}.lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def _release_tenant_sync_lock(fh) -> None:
    if fh is None:
        return
    if fcntl is None:
        fh.release()
        return
    try:
        fcntl.flock(fh, fcntl.LOCK_UN)
    finally:
        fh.close()


async def refresh_keyword_workbench_snapshot(
    session, tenant: Tenant, acc: BaiduAccount, target_date
) -> dict:
    """同步关键词工作台所需数据；定时任务和人工刷新共用同一套逻辑。"""
    lock_fh = _acquire_tenant_sync_lock(tenant.id)
    if lock_fh is None:
        return {"status": "busy", "tenant_id": tenant.id}
    try:
        report_rows = await sync_keyword_report_for_account(session, acc, target_date)
        dimension_rows = await sync_keyword_dimension_reports_for_account(
            session, acc, target_date
        )
        campaigns = await sync_campaigns_for_account(session, acc)
        adgroups = await sync_adgroups_for_account(session, acc)
        keywords = await sync_keywords_for_account(session, acc)
        strategies = await sync_price_strategies_for_account(session, acc)
        category_counts = await reclassify_keywords(session, tenant)
        return {
            "status": "ok",
            "tenant_id": tenant.id,
            "date": target_date.isoformat(),
            "report_rows_written": report_rows,
            "dimension_rows_written": dimension_rows,
            "campaigns_synced": campaigns,
            "adgroups_synced": adgroups,
            "keywords_synced": keywords,
            "price_strategies_synced": strategies,
            "category_counts": category_counts,
        }
    finally:
        _release_tenant_sync_lock(lock_fh)


def _acquire_scheduler_lock() -> bool:
    global _lock_fh
    if fcntl is None:
        return _windows_scheduler_lock.acquire(blocking=False)
    try:
        _lock_fh = open(_SCHEDULER_LOCK_PATH, "w")
        fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        if _lock_fh is not None:
            _lock_fh.close()
            _lock_fh = None
        return False


async def fetch_yesterday_keyword_report() -> None:
    """每天凌晨 2 点跑：报告 → 关键词维度 → 分级 → 规则引擎。

    维度同步/分级失败不阻断规则引擎（用上一次的分级继续跑）。
    """
    yesterday = datetime.now(_SHANGHAI_TZ).date() - timedelta(days=1)
    logger.info("[scheduler] 开始拉取 %s 关键词报告", yesterday)
    async with async_session_factory() as session:
        async with _report_sync_lock:
            result = await sync_keyword_report_for_all_active_accounts(session, yesterday)

        accounts = (
            await session.scalars(
                select(BaiduAccount).where(BaiduAccount.status == "active")
            )
        ).all()
        for acc in accounts:
            try:
                await sync_campaigns_for_account(session, acc)
                await sync_adgroups_for_account(session, acc)
                await sync_keywords_for_account(session, acc)
                await sync_price_strategies_for_account(session, acc)
                await sync_ocpc_packages_for_account(session, acc)
            except Exception:  # noqa: BLE001
                logger.exception("账户 %s 层级/关键词维度同步失败", acc.baidu_username)
            try:
                # 操作记录增量：3 天重叠窗口防漏（dedup_key 幂等，重复拉不重复入库）
                await sync_operation_records_for_account(
                    session,
                    acc,
                    datetime.now(_SHANGHAI_TZ).date() - timedelta(days=3),
                    datetime.now(_SHANGHAI_TZ).date(),
                )
            except Exception:  # noqa: BLE001
                logger.exception("账户 %s 操作记录同步失败", acc.baidu_username)
        for tenant in (await session.scalars(select(Tenant))).all():
            try:
                await reclassify_keywords(session, tenant)
            except Exception:  # noqa: BLE001
                logger.exception("租户 %s 分级重算失败", tenant.name)

        alerts = await run_rules_for_all_tenants(session, yesterday)
        try:
            suggestions = await run_suggestions_for_all_tenants(session)
        except Exception:  # noqa: BLE001
            logger.exception("[scheduler] 建议引擎执行失败（不阻断其余）")
            suggestions = {}
    logger.info(
        "[scheduler] %s 完成: 报告 %s，告警 %s，建议 %s",
        yesterday,
        result,
        alerts,
        suggestions,
    )


async def fetch_today_keyword_report() -> None:
    """每 15 分钟刷新当日报告及关键词工作台维度数据。"""
    today = datetime.now(_SHANGHAI_TZ).date()
    logger.info("[scheduler] 开始 15 分钟关键词工作台同步 %s", today)
    async with _report_sync_lock:
        async with async_session_factory() as session:
            accounts = (
                await session.scalars(
                    select(BaiduAccount).where(BaiduAccount.status == "active")
                )
            ).all()
            result = {}
            for acc in accounts:
                tenant = await session.get(Tenant, acc.tenant_id)
                if tenant is None:
                    result[acc.baidu_username] = {"status": "missing_tenant"}
                    continue
                try:
                    result[acc.baidu_username] = await refresh_keyword_workbench_snapshot(
                        session, tenant, acc, today
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "账户 %s 的 15 分钟同步失败: %s", acc.baidu_username, exc
                    )
                    result[acc.baidu_username] = {
                        "status": "error",
                        "message": str(exc),
                    }
    logger.info("[scheduler] %s 关键词工作台同步完成: %s", today, result)


async def purge_old_assistant_messages() -> None:
    """每天清理保留期外的助手对话（记忆表不受影响）。"""
    from app.ai.assistant import purge_old_messages
    async with async_session_factory() as session:
        try:
            n = await purge_old_messages(session)
            logger.info("[scheduler] 清理过期助手对话 %s 条", n)
        except Exception:  # noqa: BLE001
            logger.exception("[scheduler] 清理助手对话失败")


async def run_geo_daily_metrics_nightly() -> None:
    """Nightly: rebuild daily metrics (tenant/business/unit) for recent snapshot tenants."""
    from app.geo.content.daily_metrics import nightly_rebuild_recent_tenants

    try:
        summary = await nightly_rebuild_recent_tenants(lookback_days=2)
        logger.info("[scheduler] geo daily metrics nightly %s", summary)
    except Exception:  # noqa: BLE001
        logger.exception("[scheduler] geo daily metrics nightly failed")


async def run_geo_visibility_patrols() -> None:
    """Hourly: fire enabled tenants whose window + interval allow a run (Asia/Shanghai)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.database import async_session_factory
    from app.geo.content.patrol import execute_patrol_run, should_run_scheduled_patrol
    from app.models import GeoVisibilityPatrolRun, GeoVisibilityPatrolSettings
    from sqlalchemy import select

    from app.config import get_settings
    from app.geo.content.patrol import count_patrol_runs_today

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
            start_h = int(getattr(st, "window_start_hour", None) or st.daily_hour or 6)
            end_h = int(getattr(st, "window_end_hour", None) or st.daily_hour or 22)
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
            used = await count_patrol_runs_today(session, st.tenant_id)
            if used >= day_limit:
                logger.warning(
                    "[scheduler] skip patrol tenant=%s daily quota %s/%s",
                    st.tenant_id,
                    used,
                    day_limit,
                )
                continue
            # skip if a scheduled run is already in flight
            inflight = await session.scalar(
                select(GeoVisibilityPatrolRun.id)
                .where(
                    GeoVisibilityPatrolRun.tenant_id == st.tenant_id,
                    GeoVisibilityPatrolRun.trigger == "schedule",
                    GeoVisibilityPatrolRun.status.in_(("pending", "running")),
                )
                .limit(1)
            )
            if inflight:
                logger.info(
                    "[scheduler] skip patrol tenant=%s already inflight run=%s",
                    st.tenant_id,
                    inflight,
                )
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
            # record schedule tick immediately so interval holds even if execute fails mid-way
            st.last_scheduled_at = datetime.utcnow()
            await session.commit()
            await session.refresh(run)
            rid = run.id
            try:
                await execute_patrol_run(session, rid)
                logger.info(
                    "[scheduler] geo visibility patrol done tenant=%s run=%s window=%s-%s interval=%sh",
                    st.tenant_id,
                    rid,
                    start_h,
                    end_h,
                    interval,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[scheduler] geo visibility patrol failed tenant=%s run=%s",
                    st.tenant_id,
                    rid,
                )


def start_scheduler() -> None:
    if not _acquire_scheduler_lock():
        logger.info(
            "[scheduler] 未抢到调度锁，本 worker 不启动调度（另一 worker 已在跑，避免双跑）"
        )
        return
    scheduler.add_job(
        fetch_today_keyword_report,
        CronTrigger(minute="*/15"),
        id="fetch_today_keyword_report",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        fetch_yesterday_keyword_report,
        CronTrigger(hour=2, minute=0),
        id="fetch_yesterday_keyword_report",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        purge_old_assistant_messages,
        CronTrigger(hour=3, minute=30),
        id="purge_old_assistant_messages",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    # GEO 可见度全自动巡检：每小时检查租户时间段 + 间隔
    scheduler.add_job(
        run_geo_visibility_patrols,
        CronTrigger(minute=5),
        id="geo_visibility_patrols",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    # GEO 按天指标：每日 0:40 重算近 2 天（租户/业务/单元切片兜底）
    scheduler.add_job(
        run_geo_daily_metrics_nightly,
        CronTrigger(hour=0, minute=40),
        id="geo_daily_metrics_nightly",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info("[scheduler] 已启动，下次执行 %s", _next_run())


def _next_run() -> str | None:
    jobs = scheduler.get_jobs()
    if not jobs:
        return None
    return str(jobs[0].next_run_time)


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
