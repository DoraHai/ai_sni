"""APScheduler 定时任务。

任务清单：
  - fetch_today_keyword_report：每 15 分钟（Asia/Shanghai）
    拉取当天累计报告，并刷新计划/单元/关键词/出价策略
  - fetch_yesterday_keyword_report：每天 02:00（Asia/Shanghai）
    报告同步 → 关键词维度同步（getWord）→ 5 类分级重算 → 规则引擎
  - sync_search_terms_daily：每天 03:00（Asia/Shanghai）
    搜索词报告近 31 天同步，独立于主同步流程

在 main.py 的 startup 事件里调 start_scheduler()。
"""
import logging
from asyncio import Lock, sleep
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.baidu.sync import (
    sync_adgroups_for_account,
    sync_campaigns_for_account,
    sync_keyword_dimension_reports_for_account,
    sync_keyword_report_for_account,
    sync_keyword_report_for_all_active_accounts,
    sync_region_snapshot,
    sync_search_terms_for_account,
    sync_keywords_for_account,
    sync_ocpc_packages_for_account,
    sync_operation_records_for_account,
    sync_price_strategies_for_account,
)
from app.baidu.oauth import refresh_expiring_oauth_grants
from app.classification import reclassify_keywords
from app.database import async_session_factory
from app.models import BaiduAccount, Tenant
from app.rules import run_rules_for_all_tenants
from app.rules.site_health import run_site_health_for_all_tenants
from app.suggestions import run_suggestions_for_all_tenants

logger = logging.getLogger(__name__)

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows local tests only
    fcntl = None

scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
_report_sync_lock = Lock()
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

# 多 worker 防双跑：uvicorn --workers 2 时每个 worker 都会执行 startup → 各起一个
# APScheduler，导致每日任务跑两次（重复调百度 + 重复写）。用文件排他锁，只让抢到锁的
# 那个 worker 启动调度，其余 worker 跳过。锁随进程退出自动释放。
_SCHEDULER_LOCK_PATH = "/tmp/sem_scheduler.lock"
_lock_fh = None


def _acquire_tenant_sync_lock(tenant_id: int):
    """跨 worker 的客户级非阻塞锁，避免定时任务和人工刷新重复调用百度。"""
    fh = open(f"/tmp/sem_tenant_sync_{tenant_id}.lock", "w")
    if fcntl is None:
        return fh
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def _release_tenant_sync_lock(fh) -> None:
    if fh is None:
        return
    try:
        if fcntl is not None:
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
        acc.sync_status = "syncing"
        acc.last_sync_error = None
        if hasattr(session, "commit"):
            await session.commit()
        report_rows = await sync_keyword_report_for_account(session, acc, target_date)
        dimension_rows = await sync_keyword_dimension_reports_for_account(
            session, acc, target_date
        )
        campaigns = await sync_campaigns_for_account(session, acc)
        adgroups = await sync_adgroups_for_account(session, acc)
        keywords = await sync_keywords_for_account(session, acc)
        strategies = await sync_price_strategies_for_account(session, acc)
        category_counts = await reclassify_keywords(session, tenant)
        acc.last_synced_at = datetime.utcnow()
        acc.sync_status = "synced"
        acc.last_sync_error = None
        # 生产传 AsyncSession；单元测试可传最小 session stub。
        if hasattr(session, "commit"):
            await session.commit()
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
    except Exception as exc:
        if hasattr(session, "rollback"):
            await session.rollback()
        failed_acc = acc
        if hasattr(session, "get"):
            failed_acc = await session.get(BaiduAccount, acc.id) or acc
        failed_acc.sync_status = "failed"
        failed_acc.last_sync_error = str(exc)[:500]
        if hasattr(session, "commit"):
            await session.commit()
        raise
    finally:
        _release_tenant_sync_lock(lock_fh)


def _acquire_scheduler_lock() -> bool:
    global _lock_fh
    try:
        _lock_fh = open(_SCHEDULER_LOCK_PATH, "w")
        if fcntl is not None:
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
        refresh_result = await refresh_expiring_oauth_grants(session)
        logger.info("[scheduler] OAuth Token 刷新结果: %s", refresh_result)
        async with _report_sync_lock:
            result = await sync_keyword_report_for_all_active_accounts(session, yesterday)

        accounts = (
            await session.scalars(
                select(BaiduAccount).where(BaiduAccount.status == "active")
            )
        ).all()
        for acc in accounts:
            try:
                tenant = await session.get(Tenant, acc.tenant_id)
                if tenant is not None:
                    await sleep(2)
                    await sync_region_snapshot(session, tenant, acc, yesterday, yesterday)
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
            refresh_result = await refresh_expiring_oauth_grants(session)
            logger.info("[scheduler] OAuth Token 刷新结果: %s", refresh_result)
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


async def probe_site_health_alerts() -> None:
    """独立探测落地页可用性，避免拖慢每日报表同步链路。"""
    today = datetime.now(_SHANGHAI_TZ).date()
    logger.info("[scheduler] 开始落地页可用性探测 %s", today)
    async with async_session_factory() as session:
        result = await run_site_health_for_all_tenants(session, today)
    logger.info("[scheduler] %s 落地页可用性探测完成: %s", today, result)


async def sync_search_terms_daily() -> None:
    """每日同步近 31 天搜索词报告，避免分段拉取拖慢 02:00 主同步。"""
    end_date = datetime.now(_SHANGHAI_TZ).date()
    start_date = end_date - timedelta(days=30)
    logger.info(
        "[scheduler] 开始搜索词报告每日同步 %s~%s", start_date, end_date
    )
    result: dict[str, int] = {}
    async with _report_sync_lock:
        async with async_session_factory() as session:
            refresh_result = await refresh_expiring_oauth_grants(session)
            logger.info("[scheduler] OAuth Token 刷新结果: %s", refresh_result)
            accounts = (
                await session.scalars(
                    select(BaiduAccount).where(BaiduAccount.status == "active")
                )
            ).all()
            for acc in accounts:
                try:
                    result[acc.baidu_username] = await sync_search_terms_for_account(
                        session, acc, start_date, end_date
                    )
                    logger.info(
                        "账户 %s 搜索词报告每日同步完成: %d 条",
                        acc.baidu_username,
                        result[acc.baidu_username],
                    )
                except Exception:  # noqa: BLE001
                    await session.rollback()
                    result[acc.baidu_username] = -1
                    logger.exception("账户 %s 搜索词报告同步失败", acc.baidu_username)
    logger.info("[scheduler] 搜索词报告每日同步完成: %s", result)


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
    scheduler.add_job(
        sync_search_terms_daily,
        CronTrigger(hour=3, minute=0),
        id="sync_search_terms_daily",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        probe_site_health_alerts,
        CronTrigger(minute=20),
        id="probe_site_health_alerts",
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
