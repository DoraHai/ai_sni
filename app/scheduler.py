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
import tempfile
from asyncio import Lock, sleep
from datetime import date, datetime, timedelta
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
    sync_keyword_report_range_for_account,
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
from app.module_scope import (
    get_tenant_module,
    list_active_module_tenants,
    list_active_sem_accounts,
)
from app.process_lock import acquire_file_lock, release_file_lock
from app.rules import run_rules_for_all_tenants
from app.rules.site_health import run_site_health_for_all_tenants
from app.suggestions import run_suggestions_for_all_tenants
from app.sem_asset_sync import (
    aggregate_sync_status,
    begin_sync_run,
    finish_sync_run,
    normalize_dimensions,
    safe_sync_error,
    update_dimension,
)
from app.security.sem_identity import (
    ensure_sem_identity_access,
    filter_identity_safe_active_accounts,
)

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
_report_sync_lock = Lock()
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
INITIAL_KEYWORD_HISTORY_DAYS = 30

# 多 worker 防双跑：uvicorn --workers 2 时每个 worker 都会执行 startup → 各起一个
# APScheduler，导致每日任务跑两次（重复调百度 + 重复写）。用文件排他锁，只让抢到锁的
# 那个 worker 启动调度，其余 worker 跳过。锁随进程退出自动释放。
_LOCK_DIRECTORY = Path(tempfile.gettempdir())
_SCHEDULER_LOCK_PATH = _LOCK_DIRECTORY / "sem_scheduler.lock"
_lock_fh = None


def _acquire_tenant_sync_lock(tenant_id: int):
    """跨 worker 的客户级非阻塞锁，避免定时任务和人工刷新重复调用百度。"""
    return acquire_file_lock(_LOCK_DIRECTORY / f"sem_tenant_sync_{tenant_id}.lock")


def _release_tenant_sync_lock(fh) -> None:
    release_file_lock(fh)


async def refresh_keyword_workbench_snapshot(
    session,
    tenant: Tenant,
    acc: BaiduAccount,
    target_date: date,
    dimensions: list[str] | tuple[str, ...] | None = None,
    report_start_date: date | None = None,
) -> dict:
    """同步 SEM 只读资产；单维度失败不会阻断其他维度。"""
    tenant_id = tenant.id
    account_id = getattr(acc, "id", None)
    selected = normalize_dimensions(dimensions)
    lock_fh = _acquire_tenant_sync_lock(tenant_id)
    if lock_fh is None:
        return {"status": "busy", "tenant_id": tenant_id}
    state, run_id = begin_sync_run(getattr(acc, "asset_sync_state", None), selected)
    results: dict[str, int | dict] = {}
    failures: dict[str, str] = {}
    category_counts: dict = {}
    try:
        acc.sync_status = "syncing"
        acc.last_sync_error = None
        acc.asset_sync_state = state
        if hasattr(session, "commit"):
            await session.commit()

        async def run_dimension(name: str):
            nonlocal acc, state, tenant
            state = update_dimension(state, run_id, name, "syncing")
            acc.asset_sync_state = state
            if hasattr(session, "commit"):
                await session.commit()
            try:
                if name == "reports":
                    report_start = report_start_date or target_date
                    if report_start > target_date:
                        raise ValueError("关键词报告开始日期不能晚于结束日期")
                    report_rows = await sync_keyword_report_range_for_account(
                        session, acc, report_start, target_date
                    )
                    dimension_rows = await sync_keyword_dimension_reports_for_account(
                        session, acc, target_date
                    )
                    value: int | dict = {
                        "report": report_rows,
                        "region": int(dimension_rows.get("region", 0)),
                        "hourly": int(dimension_rows.get("hourly", 0)),
                    }
                elif name == "campaigns":
                    value = await sync_campaigns_for_account(session, acc)
                elif name == "adgroups":
                    value = await sync_adgroups_for_account(session, acc)
                elif name == "keywords":
                    value = await sync_keywords_for_account(session, acc)
                elif name == "search_terms":
                    value = await sync_search_terms_for_account(
                        session, acc, target_date - timedelta(days=30), target_date
                    )
                else:
                    value = await sync_price_strategies_for_account(session, acc)
                results[name] = value
                status = (
                    "preserved"
                    if name == "search_terms" and value == 0
                    else "empty" if value == 0 else "success"
                )
                state = update_dimension(state, run_id, name, status, rows=value)
            except Exception as exc:  # noqa: BLE001
                if hasattr(session, "rollback"):
                    await session.rollback()
                if account_id is not None and hasattr(session, "get"):
                    acc = await session.get(BaiduAccount, account_id) or acc
                    tenant = await session.get(Tenant, tenant_id) or tenant
                message = safe_sync_error(exc)
                failures[name] = message
                state = update_dimension(
                    state, run_id, name, "failed", error=message
                )
                logger.error(
                    "账户 %s 的 %s 维度同步失败: %s",
                    getattr(acc, "baidu_username", account_id),
                    name,
                    message,
                )
            acc.asset_sync_state = state
            if hasattr(session, "commit"):
                await session.commit()

        for dimension in selected:
            await run_dimension(dimension)

        if "keywords" in selected and "keywords" not in failures:
            try:
                category_counts = await reclassify_keywords(session, tenant)
            except Exception:  # noqa: BLE001
                logger.exception("租户 %s 关键词分级重算失败（不影响资产同步状态）", tenant_id)

        state = finish_sync_run(state, run_id)
        acc.asset_sync_state = state
        acc.sync_status = aggregate_sync_status(state)
        acc.last_sync_error = "；".join(
            f"{name}: {message}" for name, message in failures.items()
        ) or None
        if acc.sync_status == "synced":
            acc.last_synced_at = datetime.utcnow()
        if hasattr(session, "commit"):
            await session.commit()
        return {
            "status": "ok" if not failures else "partial",
            "tenant_id": tenant_id,
            "date": target_date.isoformat(),
            "report_start_date": (report_start_date or target_date).isoformat(),
            "selected_dimensions": list(selected),
            "dimensions": state.get("dimensions", {}),
            "report_rows_written": (results.get("reports") or {}).get("report", 0),
            "dimension_rows_written": results.get("reports") or {},
            "campaigns_synced": results.get("campaigns", 0),
            "adgroups_synced": results.get("adgroups", 0),
            "keywords_synced": results.get("keywords", 0),
            "search_terms_synced": results.get("search_terms", 0),
            "price_strategies_synced": results.get("price_strategies", 0),
            "category_counts": category_counts,
        }
    except Exception as exc:
        if hasattr(session, "rollback"):
            await session.rollback()
        failed_acc = acc
        if account_id is not None and hasattr(session, "get"):
            failed_acc = await session.get(BaiduAccount, account_id) or acc
        failed_acc.sync_status = "failed"
        failed_acc.last_sync_error = safe_sync_error(exc)
        failed_acc.asset_sync_state = finish_sync_run(state, run_id)
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


def _account_refs(accounts: list[BaiduAccount]) -> list[tuple[int, int, str]]:
    """Detach stable scalar identities before the listing session is closed."""
    return [
        (account.id, account.tenant_id, account.baidu_username)
        for account in accounts
    ]


async def _scheduled_account_refs(session) -> list[tuple[int, int, str]]:
    return _account_refs(
        filter_identity_safe_active_accounts(
            await list_active_sem_accounts(session)
        )
    )


async def _reload_scheduled_account(
    session,
    account_id: int,
    expected_tenant_id: int,
) -> tuple[BaiduAccount | None, Tenant | None, str | None]:
    """Reload and revalidate an account immediately before scheduled work."""
    account = await session.get(BaiduAccount, account_id)
    if account is None:
        return None, None, "missing_account"
    if account.status != "active" or account.tenant_id != expected_tenant_id:
        return None, None, "account_changed"
    await get_tenant_module(session, expected_tenant_id, "sem")
    await ensure_sem_identity_access(session, expected_tenant_id)
    tenant = await session.get(Tenant, expected_tenant_id)
    if tenant is None:
        return None, None, "missing_tenant"
    return account, tenant, None


async def fetch_yesterday_keyword_report() -> None:
    """每天凌晨 2 点跑：报告 → 关键词维度 → 分级 → 规则引擎。

    维度同步/分级失败不阻断规则引擎（用上一次的分级继续跑）。
    """
    yesterday = datetime.now(_SHANGHAI_TZ).date() - timedelta(days=1)
    logger.info("[scheduler] 开始拉取 %s 关键词报告", yesterday)
    result: dict[str, int] = {}
    async with _report_sync_lock:
        async with async_session_factory() as session:
            refresh_result = await refresh_expiring_oauth_grants(session)
            logger.info("[scheduler] OAuth Token 刷新结果: %s", refresh_result)
            account_refs = await _scheduled_account_refs(session)

        for account_id, tenant_id, username in account_refs:
            try:
                async with async_session_factory() as session:
                    acc, _tenant, skipped = await _reload_scheduled_account(
                        session, account_id, tenant_id
                    )
                    if skipped is not None or acc is None:
                        result[username] = -1
                        continue
                    report_rows = await sync_keyword_report_for_account(
                        session, acc, yesterday
                    )
                    await sync_keyword_dimension_reports_for_account(
                        session, acc, yesterday
                    )
                    result[username] = report_rows
            except Exception as exc:  # noqa: BLE001
                result[username] = -1
                logger.exception(
                    "账户 %s 拉 %s 报告失败: %s",
                    username,
                    yesterday,
                    safe_sync_error(exc),
                )

    for account_id, tenant_id, username in account_refs:
        try:
            async with async_session_factory() as session:
                acc, tenant, skipped = await _reload_scheduled_account(
                    session, account_id, tenant_id
                )
                if skipped is not None or acc is None or tenant is None:
                    continue
                await sleep(2)
                await sync_region_snapshot(session, tenant, acc, yesterday, yesterday)
                await sync_campaigns_for_account(session, acc)
                await sync_adgroups_for_account(session, acc)
                await sync_keywords_for_account(session, acc)
                await sync_price_strategies_for_account(session, acc)
                await sync_ocpc_packages_for_account(session, acc)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "账户 %s 层级/关键词维度同步失败: %s",
                username,
                safe_sync_error(exc),
            )

        try:
            async with async_session_factory() as session:
                acc, _tenant, skipped = await _reload_scheduled_account(
                    session, account_id, tenant_id
                )
                if skipped is not None or acc is None:
                    continue
                # 操作记录增量：3 天重叠窗口防漏（dedup_key 幂等，重复拉不重复入库）
                await sync_operation_records_for_account(
                    session,
                    acc,
                    datetime.now(_SHANGHAI_TZ).date() - timedelta(days=3),
                    datetime.now(_SHANGHAI_TZ).date(),
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "账户 %s 操作记录同步失败: %s",
                username,
                safe_sync_error(exc),
            )

    async with async_session_factory() as session:
        tenant_refs = [
            (tenant.id, tenant.name)
            for tenant in await list_active_module_tenants(session, "sem")
        ]
    for tenant_id, tenant_name in tenant_refs:
        try:
            async with async_session_factory() as session:
                await get_tenant_module(session, tenant_id, "sem")
                await ensure_sem_identity_access(session, tenant_id)
                tenant = await session.get(Tenant, tenant_id)
                if tenant is not None:
                    await reclassify_keywords(session, tenant)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "租户 %s 分级重算失败: %s",
                tenant_name,
                safe_sync_error(exc),
            )

    async with async_session_factory() as session:
        alerts = await run_rules_for_all_tenants(session, yesterday)
    try:
        async with async_session_factory() as session:
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
            # A failed dimension sync can roll back the shared session. SQLAlchemy
            # expires every ORM object on rollback, including accounts that have
            # not been processed yet. Keep only scalar identities across account
            # iterations and reload each account in the active async context.
            account_refs = await _scheduled_account_refs(session)
        result = {}
        for account_id, tenant_id, username in account_refs:
            try:
                async with async_session_factory() as session:
                    acc, tenant, skipped = await _reload_scheduled_account(
                        session, account_id, tenant_id
                    )
                    if skipped is not None or acc is None or tenant is None:
                        result[username] = {"status": skipped or "account_unavailable"}
                        continue
                    result[username] = await refresh_keyword_workbench_snapshot(
                        session, tenant, acc, today
                    )
            except Exception as exc:  # noqa: BLE001
                # The per-account context owns transaction cleanup. Catch outside
                # it so a rollback/close failure cannot abort later accounts.
                message = safe_sync_error(exc)
                logger.exception(
                    "账户 %s 的 15 分钟同步失败: %s", username, message
                )
                result[username] = {
                    "status": "error",
                    "message": message,
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
            account_refs = await _scheduled_account_refs(session)
        for account_id, tenant_id, username in account_refs:
            try:
                async with async_session_factory() as session:
                    acc, _tenant, skipped = await _reload_scheduled_account(
                        session, account_id, tenant_id
                    )
                    if skipped is not None or acc is None:
                        result[username] = -1
                        continue
                    result[username] = await sync_search_terms_for_account(
                        session, acc, start_date, end_date
                    )
                    logger.info(
                        "账户 %s 搜索词报告每日同步完成: %d 条",
                        username,
                        result[username],
                    )
            except Exception as exc:  # noqa: BLE001
                result[username] = -1
                logger.exception(
                    "账户 %s 搜索词报告同步失败: %s",
                    username,
                    safe_sync_error(exc),
                )
    logger.info("[scheduler] 搜索词报告每日同步完成: %s", result)


async def check_writeback_health() -> None:
    """Independent transactions prevent one customer's failure blocking others."""
    from app.rules.writeback_health import refresh_writeback_alerts

    async with async_session_factory() as session:
        tenant_ids = [t.id for t in await list_active_module_tenants(session, "sem")]
    for tenant_id in tenant_ids:
        try:
            async with async_session_factory() as session:
                await refresh_writeback_alerts(session, tenant_id)
                await session.commit()
        except Exception:  # noqa: BLE001
            logger.exception("[scheduler] 回写告警检查失败 tenant=%s", tenant_id)


def start_scheduler() -> None:
    if not _acquire_scheduler_lock():
        logger.info(
            "[scheduler] 未抢到调度锁，本 worker 不启动调度（另一 worker 已在跑，避免双跑）"
        )
        return
    try:
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
            CronTrigger(hour=4, minute=20),
            id="probe_site_health_alerts",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        scheduler.add_job(
            check_writeback_health,
            CronTrigger(minute="*/5"),
            id="check_writeback_health",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
    except Exception:
        _release_scheduler_lock()
        raise
    logger.info("[scheduler] 已启动，下次执行 %s", _next_run())


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
