"""APScheduler 定时任务。

任务清单：
  - fetch_today_keyword_report：每 15 分钟（Asia/Shanghai）
    拉取当天累计报告，并刷新计划/单元/关键词/出价策略
  - fetch_yesterday_keyword_report：每天 02:00（Asia/Shanghai）
    报告同步 → 关键词维度同步（getWord）→ 5 类分级重算 → 规则引擎
  - collect_daily_seo_rankings：每天 02:00（Asia/Shanghai）
    遍历全部启用 SEO 关键词，采集百度 PC/移动前 50 并写入品牌排名快照

在 main.py 的 startup 事件里调 start_scheduler()。
"""
import logging
import tempfile
from asyncio import Lock
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
    sync_keywords_for_account,
    sync_ocpc_packages_for_account,
    sync_operation_records_for_account,
    sync_price_strategies_for_account,
)
from app.baidu.oauth import refresh_expiring_oauth_grants
from app.classification import reclassify_keywords
from app.config import get_settings
from app.database import async_session_factory
from app.models import BaiduAccount, SeoKeywordAsset, SeoRankSnapshot, Tenant
from app.process_lock import acquire_file_lock, release_file_lock
from app.rules import run_rules_for_all_tenants
from app.suggestions import run_suggestions_for_all_tenants

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
_report_sync_lock = Lock()
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

# 多 worker 防双跑：uvicorn --workers 2 时每个 worker 都会执行 startup → 各起一个
# APScheduler，导致每日任务跑两次（重复调百度 + 重复写）。用文件排他锁，只让抢到锁的
# 那个 worker 启动调度，其余 worker 跳过。锁随进程退出自动释放。
_LOCK_DIR = Path(tempfile.gettempdir())
_SCHEDULER_LOCK_PATH = _LOCK_DIR / "sem_scheduler.lock"
_SEO_RANK_LOCK_PATH = _LOCK_DIR / "sem_seo_rank_collection.lock"
_lock_fh = None


def _acquire_tenant_sync_lock(tenant_id: int):
    """跨 worker 的客户级非阻塞锁，避免定时任务和人工刷新重复调用百度。"""
    return acquire_file_lock(_LOCK_DIR / f"sem_tenant_sync_{tenant_id}.lock")


def _release_tenant_sync_lock(fh) -> None:
    release_file_lock(fh)


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
    _lock_fh = acquire_file_lock(_SCHEDULER_LOCK_PATH)
    return _lock_fh is not None


def _release_scheduler_lock() -> None:
    global _lock_fh
    release_file_lock(_lock_fh)
    _lock_fh = None


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


def _chunks(values: list[int], size: int) -> list[list[int]]:
    size = max(1, size)
    return [values[index : index + size] for index in range(0, len(values), size)]


def _local_day_start_utc(now: datetime | None = None) -> datetime:
    """返回上海自然日零点对应的无时区 UTC 时间，匹配数据库 DateTime 字段。"""
    local_now = now or datetime.now(_SHANGHAI_TZ)
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_start.astimezone(timezone.utc).replace(tzinfo=None)


async def collect_daily_seo_rankings() -> None:
    """每天 02:00 采集全部客户的百度 PC/移动前 50 排名。

    已在当天成功形成快照的关键词/设备会跳过，因此任务重试不会重复扣费；
    每批共用同一个 captured_at，前端可以完整读取本次全量批次。
    """
    settings = get_settings()
    if not settings.seo_rank_scheduler_enabled:
        logger.info("[scheduler][SEO] 自动排名采集已关闭")
        return

    lock_fh = acquire_file_lock(_SEO_RANK_LOCK_PATH)
    if lock_fh is None:
        logger.info("[scheduler][SEO] 另一排名采集任务正在运行，本次跳过")
        return

    # 延迟导入，避免 scheduler 与 SEO 路由在应用启动时形成循环依赖。
    from app.api.seo import collect_rank_serp_for_tenant

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
    }
    try:
        async with async_session_factory() as session:
            tenant_ids = list(
                await session.scalars(
                    select(SeoKeywordAsset.tenant_id)
                    .where(SeoKeywordAsset.status == "active")
                    .distinct()
                    .order_by(SeoKeywordAsset.tenant_id)
                )
            )
            for tenant_id in tenant_ids:
                keyword_ids = list(
                    await session.scalars(
                        select(SeoKeywordAsset.id)
                        .where(
                            SeoKeywordAsset.tenant_id == tenant_id,
                            SeoKeywordAsset.status == "active",
                        )
                        .order_by(SeoKeywordAsset.priority, SeoKeywordAsset.id)
                    )
                )
                if not keyword_ids:
                    continue
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
                    pending_ids = [
                        keyword_id
                        for keyword_id in keyword_ids
                        if (keyword_id, device) not in completed
                    ]
                    totals["skipped_pairs"] += len(keyword_ids) - len(pending_ids)
                    for keyword_batch in _chunks(
                        pending_ids, settings.seo_rank_scheduler_batch_size
                    ):
                        try:
                            result = await collect_rank_serp_for_tenant(
                                session=session,
                                tenant_id=tenant_id,
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
                                "[scheduler][SEO] 客户 %s 的 %s 批次采集失败（关键词 %s 个）",
                                tenant_id,
                                device,
                                len(keyword_batch),
                            )
                            continue
                        totals["requests"] += result["requests"]
                        totals["snapshots"] += result["snapshots"]
                        totals["serp_results"] += result["serp_results"]
                        totals["errors"] += len(result["errors"])
        logger.info("[scheduler][SEO] 每日百度前 50 排名采集完成: %s", totals)
    finally:
        release_file_lock(lock_fh)


def _start_scheduler() -> None:
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
        collect_daily_seo_rankings,
        CronTrigger(hour=2, minute=0),
        id="collect_daily_seo_rankings",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        purge_old_assistant_messages,
        CronTrigger(hour=3, minute=30),
        id="purge_old_assistant_messages",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info("[scheduler] 已启动，下次执行 %s", _next_run())


def start_scheduler() -> None:
    try:
        _start_scheduler()
    except Exception:
        _release_scheduler_lock()
        raise


def _next_run() -> str | None:
    jobs = scheduler.get_jobs()
    if not jobs:
        return None
    return str(jobs[0].next_run_time)


def shutdown_scheduler() -> None:
    try:
        if scheduler.running:
            scheduler.shutdown(wait=False)
    finally:
        _release_scheduler_lock()
