from __future__ import annotations

import asyncio
import logging
import unicodedata
from collections import Counter, defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, literal, select, text, union_all
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.database import Base, async_session_factory, get_session
from app.models import (
    Adgroup,
    BaiduAccount,
    BaiduOAuthGrant,
    Campaign,
    GeoProject,
    Keyword,
    SearchTermReport,
    SeoSite,
    Tenant,
    TenantModule,
)
from app.models.seo import (
    SeoBacklink,
    SeoBrandAsset,
    SeoCompetitor,
    SeoCompetitorEvent,
    SeoContentAsset,
    SeoCrawlRun,
    SeoInternalLink,
    SeoKeywordAsset,
    SeoMetricSnapshot,
    SeoPageSnapshot,
    SeoRankSnapshot,
    SeoSerpResult,
    SeoSitePage,
)
from app.module_scope import (
    MODULE_CODES,
    ensure_module_access,
    get_tenant_module,
    module_is_available,
    normalize_module_code,
)
from app.security.auth import AuthContext, require_auth, require_scoped_auth
from app.sem_asset_sync import public_sync_error


router = APIRouter(tags=["客户与模块"])
seo_sites_router = APIRouter(tags=["SEO 网站"])
geo_projects_router = APIRouter(tags=["GEO 项目"])
logger = logging.getLogger(__name__)


# Explicit allow-list for read-only SEM identity repair previews. Shared tenant
# metadata and every SEO/GEO table are deliberately excluded: this endpoint is
# diagnostic only and must never imply that cross-module data can be moved as
# part of a SEM repair.
SEM_IDENTITY_REPAIR_TABLES: tuple[tuple[str, str], ...] = (
    ("baidu_accounts", "identity"),
    ("baidu_oauth_grants", "identity"),
    ("baidu_oauth_states", "identity"),
    ("campaigns", "assets"),
    ("adgroups", "assets"),
    ("keywords", "assets"),
    ("price_strategies", "assets"),
    ("ocpc_packages", "assets"),
    ("kw_report_snapshots", "history"),
    ("kw_region_snapshots", "history"),
    ("keyword_region_reports", "history"),
    ("keyword_hourly_reports", "history"),
    ("search_term_reports", "history"),
    ("operation_records", "history"),
    ("keyword_candidates", "workflow"),
    ("suggestions", "workflow"),
    ("alerts", "workflow"),
    ("daily_insights", "workflow"),
    ("monthly_reports", "workflow"),
    ("analysis_reports", "workflow"),
    ("assistant_messages", "workflow"),
    ("tenant_memories", "workflow"),
    ("leads", "workflow"),
    ("adjustment_reviews", "writeback_audit"),
    ("bid_writebacks", "writeback_audit"),
    ("writeback_actions", "writeback_audit"),
    ("writeback_approvals", "writeback_audit"),
)
SEM_IDENTITY_REPAIR_MAX_CONCURRENCY = 2
SEM_IDENTITY_REPAIR_QUEUE_TIMEOUT_SECONDS = 1.0
SEM_IDENTITY_REPAIR_REQUEST_TIMEOUT_SECONDS = 20.0
SEM_IDENTITY_REPAIR_DISCONNECT_POLL_SECONDS = 0.05
_sem_identity_repair_slots = asyncio.BoundedSemaphore(
    SEM_IDENTITY_REPAIR_MAX_CONCURRENCY
)


async def require_customer_admin(ctx: AuthContext = Depends(require_auth)) -> AuthContext:
    """Platform customer master data is never editable from a tenant-bound account."""
    if ctx.tenant_id is not None or not ctx.can_edit("settings.customers"):
        raise HTTPException(403, "仅平台超级管理员可以维护客户与模块")
    return ctx


def _canonical_domain(value: str) -> tuple[str, str]:
    raw = str(value or "").strip()
    if not raw:
        raise HTTPException(400, "请填写网站域名")
    candidate = raw if "://" in raw else f"https://{raw}"
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower().strip(".")
    if not host or "." not in host:
        raise HTTPException(400, "网站域名格式不正确")
    if host.startswith("www."):
        host = host[4:]
    return host, candidate


def _module_payload(row: TenantModule) -> dict:
    return {
        "id": row.id,
        "module_code": row.module_code,
        "status": row.status,
        "available": module_is_available(row),
        "opened_at": row.opened_at.isoformat() if row.opened_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


def _sem_identity_check(tenants: list[Tenant], accounts: list[BaiduAccount]) -> dict:
    """只读检查客户与百度账户的结构性归属冲突，不根据显示名称猜测归属。"""
    issues_by_tenant: dict[int, list[dict]] = {tenant.id: [] for tenant in tenants}
    all_issues: list[dict] = []
    accounts_by_ucid: dict[int, list[BaiduAccount]] = {}
    accounts_by_tenant_ucid: dict[tuple[int, int], list[BaiduAccount]] = {}
    for account in accounts:
        status = getattr(account, "status", "active")
        if status == "identity_conflict":
            issue = {
                "code": "quarantined_account_binding",
                "severity": "warning",
                "message": f"UCID {account.baidu_ucid} 的历史错误绑定已隔离，等待复核归档",
                "ucid": str(account.baidu_ucid),
                "account_ids": [account.id],
            }
            all_issues.append(issue)
            issues_by_tenant.setdefault(account.tenant_id, []).append(issue)
        if status != "active":
            continue
        accounts_by_ucid.setdefault(account.baidu_ucid, []).append(account)
        accounts_by_tenant_ucid.setdefault(
            (account.tenant_id, account.baidu_ucid), []
        ).append(account)

    for ucid, rows in accounts_by_ucid.items():
        tenant_ids = sorted({row.tenant_id for row in rows})
        if len(tenant_ids) <= 1:
            continue
        issue = {
            "code": "ucid_cross_tenant",
            "severity": "error",
            "message": f"百度账户 UCID {ucid} 同时绑定了多个客户",
            "ucid": str(ucid),
            "tenant_ids": tenant_ids,
            "account_ids": [row.id for row in rows],
        }
        all_issues.append(issue)
        for tenant_id in tenant_ids:
            issues_by_tenant.setdefault(tenant_id, []).append(issue)

    for (tenant_id, ucid), rows in accounts_by_tenant_ucid.items():
        if len(rows) <= 1:
            continue
        issue = {
            "code": "duplicate_account_rows",
            "severity": "warning",
            "message": f"UCID {ucid} 在当前客户下存在 {len(rows)} 条账户记录",
            "ucid": str(ucid),
            "account_ids": [row.id for row in rows],
            "auth_modes": sorted({row.auth_mode for row in rows}),
        }
        all_issues.append(issue)
        issues_by_tenant.setdefault(tenant_id, []).append(issue)

    for tenant in tenants:
        if tenant.baidu_ucid is None:
            continue
        if (tenant.id, tenant.baidu_ucid) not in accounts_by_tenant_ucid:
            issue = {
                "code": "primary_ucid_missing",
                "severity": "warning",
                "message": f"客户主 UCID {tenant.baidu_ucid} 没有对应的推广账户记录",
                "ucid": str(tenant.baidu_ucid),
            }
            all_issues.append(issue)
            issues_by_tenant[tenant.id].append(issue)

    error_count = sum(
        issue["severity"] == "error"
        for issue in all_issues
    )
    warning_count = sum(
        issue["severity"] == "warning"
        for issue in all_issues
    )
    return {
        "issues_by_tenant": issues_by_tenant,
        "issues": all_issues,
        "summary": {
            "checked_customers": len(tenants),
            "checked_accounts": len(accounts),
            "errors": error_count,
            "warnings": warning_count,
            "healthy": error_count == 0 and warning_count == 0,
        },
    }


def _normalized_customer_name(value: str) -> str:
    """Normalize only casing and whitespace; do not guess brand equivalence."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(normalized.split())


def _sem_duplicate_candidate_groups(
    tenants: list[Tenant], accounts: list[BaiduAccount]
) -> list[dict]:
    """Find exact normalized-name duplicates without inferring an owner."""
    grouped: dict[str, list[Tenant]] = defaultdict(list)
    accounts_by_tenant: dict[int, list[BaiduAccount]] = defaultdict(list)
    for tenant in tenants:
        key = _normalized_customer_name(tenant.name)
        if key:
            grouped[key].append(tenant)
    for account in accounts:
        accounts_by_tenant[account.tenant_id].append(account)

    result: list[dict] = []
    for normalized_name, rows in sorted(grouped.items()):
        if len(rows) < 2:
            continue
        candidates = []
        for tenant in sorted(rows, key=lambda item: item.id):
            tenant_accounts = accounts_by_tenant.get(tenant.id, [])
            candidates.append(
                {
                    "tenant_id": tenant.id,
                    "name": tenant.name,
                    "baidu_ucid": (
                        str(tenant.baidu_ucid) if tenant.baidu_ucid is not None else None
                    ),
                    "created_at": (
                        tenant.created_at.isoformat()
                        if getattr(tenant, "created_at", None)
                        else None
                    ),
                    "account_count": len(tenant_accounts),
                    "active_account_ucids": sorted(
                        {
                            str(account.baidu_ucid)
                            for account in tenant_accounts
                            if account.status == "active"
                        }
                    ),
                }
            )
        result.append(
            {
                "normalized_name": normalized_name,
                "reason": "same_normalized_customer_name",
                "customers": candidates,
            }
        )
    return result


def _sem_identity_candidate_tenant_ids(
    tenants: list[Tenant],
    modules: list[TenantModule],
    accounts: list[BaiduAccount],
    oauth_grant_tenant_ids: set[int],
) -> set[int]:
    """Limit duplicate-name detection to customers with explicit SEM evidence."""
    eligible = {
        tenant.id for tenant in tenants if tenant.baidu_ucid is not None
    }
    eligible.update(
        row.tenant_id
        for row in modules
        if row.module_code == "sem" and module_is_available(row)
    )
    eligible.update(account.tenant_id for account in accounts)
    eligible.update(oauth_grant_tenant_ids)
    return eligible


def _sem_identity_account_select():
    """Load only non-secret account identity fields used by admin diagnostics."""
    return select(BaiduAccount).options(
        load_only(
            BaiduAccount.id,
            BaiduAccount.tenant_id,
            BaiduAccount.baidu_username,
            BaiduAccount.baidu_ucid,
            BaiduAccount.auth_mode,
            BaiduAccount.status,
        )
    )


async def _start_sem_identity_read_transaction(session: AsyncSession) -> None:
    """Make every statement in one diagnostic request share a read-only snapshot."""
    await session.execute(
        text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
    )
    await session.execute(text("SET LOCAL statement_timeout = '15s'"))


async def _get_sem_identity_snapshot_session() -> AsyncIterator[AsyncSession]:
    """Use a fresh session so authentication queries cannot precede SET TRANSACTION."""
    async with async_session_factory() as session:
        yield session


async def _run_sem_identity_repair_diagnostic(
    operation: Callable[[], Awaitable[dict]],
    request: Request | None = None,
) -> dict:
    """Bound expensive admin diagnostics independently from the shared DB pool."""
    try:
        await asyncio.wait_for(
            _sem_identity_repair_slots.acquire(),
            timeout=SEM_IDENTITY_REPAIR_QUEUE_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise HTTPException(429, "SEM 客户诊断正在运行，请稍后重试") from exc

    operation_task = None
    disconnect_task = None
    disconnect_stop = asyncio.Event()
    tasks: set[asyncio.Task] = set()
    try:
        operation_task = asyncio.create_task(operation())
        tasks.add(operation_task)
        if request is not None:
            disconnect_task = asyncio.create_task(
                _wait_for_sem_identity_client_disconnect(request, disconnect_stop)
            )
            tasks.add(disconnect_task)
        done, _pending = await asyncio.wait(
            tasks,
            timeout=SEM_IDENTITY_REPAIR_REQUEST_TIMEOUT_SECONDS,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if operation_task in done:
            try:
                return await operation_task
            except TimeoutError as exc:
                raise HTTPException(
                    503, "SEM 客户诊断超时，请缩小范围或稍后重试"
                ) from exc
        if disconnect_task is not None and disconnect_task in done:
            await disconnect_task
            raise HTTPException(499, "客户端已断开，SEM 客户诊断已取消")
        raise HTTPException(503, "SEM 客户诊断超时，请缩小范围或稍后重试")
    finally:
        disconnect_stop.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        _sem_identity_repair_slots.release()


async def _wait_for_sem_identity_client_disconnect(
    request: Request, stop: asyncio.Event
) -> None:
    while not stop.is_set():
        if await request.is_disconnected():
            return
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=SEM_IDENTITY_REPAIR_DISCONNECT_POLL_SECONDS
            )
        except TimeoutError:
            pass


def _set_sem_identity_repair_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


async def _sem_identity_repair_row_counts(
    session: AsyncSession, tenant_ids: tuple[int, int]
) -> dict[int, dict[str, int]]:
    counts = {
        tenant_id: {table_name: 0 for table_name, _category in SEM_IDENTITY_REPAIR_TABLES}
        for tenant_id in tenant_ids
    }
    count_statements = []
    for table_name, _category in SEM_IDENTITY_REPAIR_TABLES:
        table = Base.metadata.tables[table_name]
        statement = (
            select(table.c.tenant_id, func.count())
            .add_columns(literal(table_name).label("table_name"))
            .where(table.c.tenant_id.in_(tenant_ids))
            .group_by(table.c.tenant_id)
        )
        if table_name == "baidu_oauth_states":
            # OAuth state is short-lived replay protection, not durable customer
            # identity. Historical consumed/expired rows must not make this
            # diagnostic scan grow without bound.
            statement = statement.where(
                table.c.consumed_at.is_(None),
                table.c.expires_at > func.now(),
            )
        count_statements.append(statement)
    result = await session.execute(union_all(*count_statements))
    for tenant_id, count, table_name in result.all():
        counts[int(tenant_id)][str(table_name)] = int(count or 0)
    return counts


def _sem_identity_repair_preview_payload(
    source: Tenant,
    target: Tenant,
    accounts: list[BaiduAccount],
    row_counts: dict[int, dict[str, int]],
    active_oauth_grant_tenant_ids: set[int] | None = None,
) -> dict:
    """Build a fail-closed preview. This function never decides or executes a merge."""
    accounts_by_tenant: dict[int, list[BaiduAccount]] = defaultdict(list)
    for account in accounts:
        accounts_by_tenant[account.tenant_id].append(account)

    source_counts = row_counts.get(source.id, {})
    target_counts = row_counts.get(target.id, {})
    source_accounts = accounts_by_tenant.get(source.id, [])
    target_accounts = accounts_by_tenant.get(target.id, [])
    active_oauth_grant_tenant_ids = active_oauth_grant_tenant_ids or set()
    source_active_accounts = [
        account for account in source_accounts if account.status == "active"
    ]
    target_active_accounts = [
        account for account in target_accounts if account.status == "active"
    ]
    source_active_ucids = {
        account.baidu_ucid for account in source_active_accounts
    }
    target_active_ucids = {
        account.baidu_ucid for account in target_active_accounts
    }
    source_active_ucid_counts = Counter(
        account.baidu_ucid
        for account in source_accounts
        if account.status == "active"
    )
    target_active_ucid_counts = Counter(
        account.baidu_ucid
        for account in target_accounts
        if account.status == "active"
    )
    source_ucid_evidence = set(source_active_ucids)
    target_ucid_evidence = set(target_active_ucids)
    if source.baidu_ucid is not None:
        source_ucid_evidence.add(source.baidu_ucid)
    if target.baidu_ucid is not None:
        target_ucid_evidence.add(target.baidu_ucid)

    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if any(
        account.status == "identity_conflict"
        for account in source_accounts + target_accounts
    ):
        blockers.append(
            {
                "code": "quarantined_account_binding",
                "message": "来源或目标客户存在已隔离的错误账户绑定，必须先完成归属复核。",
            }
        )
    if _normalized_customer_name(source.name) != _normalized_customer_name(target.name):
        blockers.append(
            {
                "code": "customer_names_differ",
                "message": "两个客户名称不一致，不能按重复客户进行预演。",
            }
        )
    if (
        source_ucid_evidence
        and target_ucid_evidence
        and source_ucid_evidence != target_ucid_evidence
    ):
        blockers.append(
            {
                "code": "ucid_evidence_conflict",
                "message": "两个客户的主 UCID 或生效推广账户 UCID 证据不一致，禁止自动合并。",
            }
        )
    duplicate_active_ucids = source_active_ucids & target_active_ucids
    if duplicate_active_ucids:
        blockers.append(
            {
                "code": "duplicate_active_account_bindings",
                "message": "两个客户存在相同 UCID 的生效推广账户，必须先确认保留记录并归档重复绑定。",
            }
        )
    duplicate_within_customer = {
        "source": sorted(
            ucid for ucid, count in source_active_ucid_counts.items() if count > 1
        ),
        "target": sorted(
            ucid for ucid, count in target_active_ucid_counts.items() if count > 1
        ),
    }
    if duplicate_within_customer["source"] or duplicate_within_customer["target"]:
        blockers.append(
            {
                "code": "duplicate_active_accounts_within_customer",
                "message": "来源或目标客户内部存在相同 UCID 的重复生效账户，必须先归档重复记录。",
            }
        )

    source_history = sum(
        source_counts.get(table_name, 0)
        for table_name, category in SEM_IDENTITY_REPAIR_TABLES
        if category in {"assets", "history", "workflow", "writeback_audit"}
    )
    target_history = sum(
        target_counts.get(table_name, 0)
        for table_name, category in SEM_IDENTITY_REPAIR_TABLES
        if category in {"assets", "history", "workflow", "writeback_audit"}
    )
    source_identity = (
        int(source.baidu_ucid is not None)
        + len(source_active_accounts)
        + int(source.id in active_oauth_grant_tenant_ids)
    )
    target_identity = (
        int(target.baidu_ucid is not None)
        + len(target_active_accounts)
        + int(target.id in active_oauth_grant_tenant_ids)
    )
    source_writeback_audit = sum(
        source_counts.get(table_name, 0)
        for table_name, category in SEM_IDENTITY_REPAIR_TABLES
        if category == "writeback_audit"
    )
    if source_counts.get("baidu_oauth_states", 0) or target_counts.get(
        "baidu_oauth_states", 0
    ):
        blockers.append(
            {
                "code": "pending_oauth_authorization",
                "message": "来源或目标客户仍有未完成的 OAuth 授权请求，必须等待授权完成或过期后重新预演。",
            }
        )
    if (
        source_counts.get("baidu_oauth_grants", 0)
        and target_counts.get("baidu_oauth_grants", 0)
    ):
        blockers.append(
            {
                "code": "both_customers_have_oauth_grants",
                "message": "两个客户均有 OAuth 授权主记录，必须人工确定保留授权并处理账户引用。",
            }
        )
    if source_writeback_audit:
        blockers.append(
            {
                "code": "source_has_writeback_audit_history",
                "message": "来源客户存在写回或审批审计记录，必须保留原始归属并制定专项处理方案。",
            }
        )
    if source_history and target_history:
        blockers.append(
            {
                "code": "both_customers_have_sem_history",
                "message": "两个客户均有 SEM 历史数据，需逐表处理唯一约束和冲突记录。",
            }
        )
    elif source_history and target_identity == 0:
        blockers.append(
            {
                "code": "target_customer_has_no_sem_footprint",
                "message": "来源客户有 SEM 历史，但拟保留客户没有 SEM 历史或身份记录，可能选反了迁移方向。",
            }
        )
    elif source_history:
        warnings.append(
            {
                "code": "target_customer_has_identity_only",
                "message": "拟保留客户只有 SEM 身份记录、没有历史数据，必须确认它确实是正确主档。",
            }
        )
    elif source_identity == 0:
        warnings.append(
            {
                "code": "source_customer_has_no_sem_history",
                "message": "来源客户没有核心 SEM 历史数据，可能是授权误建的空壳客户。",
            }
        )
    else:
        warnings.append(
            {
                "code": "source_customer_has_identity_only",
                "message": "来源客户没有核心 SEM 历史，但仍有账户或授权身份记录，不能按空壳客户处理。",
            }
        )

    operations = [
        {
            "table": table_name,
            "category": category,
            "source_rows": source_counts.get(table_name, 0),
            "target_rows": target_counts.get(table_name, 0),
            "proposed_action": (
                "blocked_preserve_audit_provenance"
                if blockers and category == "writeback_audit"
                else "blocked_no_reassignment"
                if blockers
                else "manual_identity_resolution_required"
                if category == "identity"
                else "preserve_audit_provenance_manual_review"
                if category == "writeback_audit"
                else "review_then_reassign_tenant_id"
            ),
        }
        for table_name, category in SEM_IDENTITY_REPAIR_TABLES
        if source_counts.get(table_name, 0) or target_counts.get(table_name, 0)
    ]

    def tenant_payload(tenant: Tenant, tenant_accounts: list[BaiduAccount], counts: dict) -> dict:
        return {
            "tenant_id": tenant.id,
            "name": tenant.name,
            "baidu_ucid": str(tenant.baidu_ucid) if tenant.baidu_ucid is not None else None,
            "accounts": [
                {
                    "id": account.id,
                    "username": account.baidu_username,
                    "ucid": str(account.baidu_ucid),
                    "status": account.status,
                    "auth_mode": account.auth_mode,
                }
                for account in tenant_accounts
            ],
            "row_counts": counts,
        }

    return {
        "mode": "read_only_preview",
        "source": tenant_payload(source, source_accounts, source_counts),
        "target": tenant_payload(target, target_accounts, target_counts),
        "blockers": blockers,
        "warnings": warnings,
        "proposed_operations": operations,
        "excluded_scope": [
            "tenant_modules",
            "users",
            "api_audit_logs",
            "seo_*",
            "geo_*",
        ],
        "required_reviews": [
            "customer_identity_owner_confirmation",
            "unique_constraint_and_foreign_key_review",
            "database_backup_and_rollback_plan",
            "separate_database_change_approval",
        ],
        "safety": {
            "read_only": True,
            "writes_performed": 0,
            "execution_endpoint_available": False,
            "migration": "not-run",
        },
    }


class CustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    industry: str | None = Field(None, max_length=100)
    business_desc: str | None = Field(None, max_length=4000)
    modules: list[str] = Field(default_factory=lambda: ["sem"])


class CustomerUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    industry: str | None = Field(None, max_length=100)
    business_desc: str | None = Field(None, max_length=4000)
    confirm_bound_name_change: bool = False
    name_change_reason: str | None = Field(None, max_length=500)


class ModuleUpdate(BaseModel):
    status: str = Field(pattern="^(active|trial|suspended|closed)$")
    expires_at: date | None = None


class SemAccountArchive(BaseModel):
    reason: str = Field(min_length=4, max_length=500)


@router.get("/api/v1/admin/customers", dependencies=[Depends(require_customer_admin)])
async def list_customers(session: AsyncSession = Depends(get_session)) -> dict:
    tenants = list((await session.scalars(select(Tenant).order_by(Tenant.id))).all())
    modules = list((await session.scalars(select(TenantModule).order_by(TenantModule.id))).all())
    accounts = list(
        (
            await session.scalars(
                _sem_identity_account_select().order_by(BaiduAccount.id)
            )
        ).all()
    )
    identity_check = _sem_identity_check(tenants, accounts)
    by_tenant: dict[int, list[dict]] = {}
    for row in modules:
        by_tenant.setdefault(row.tenant_id, []).append(_module_payload(row))
    accounts_by_tenant: dict[int, list[dict]] = {}
    for account in accounts:
        accounts_by_tenant.setdefault(account.tenant_id, []).append(
            {
                "id": account.id,
                "username": account.baidu_username,
                "ucid": str(account.baidu_ucid),
                "auth_mode": account.auth_mode,
                "status": account.status,
            }
        )
    return {
        "identity_summary": identity_check["summary"],
        "customers": [
            {
                "id": row.id,
                "name": row.name,
                "industry": row.industry,
                "business_desc": row.business_desc,
                "baidu_ucid": str(row.baidu_ucid) if row.baidu_ucid is not None else None,
                "sem_accounts": accounts_by_tenant.get(row.id, []),
                "identity_locked": bool(accounts_by_tenant.get(row.id)),
                "identity_issues": identity_check["issues_by_tenant"].get(row.id, []),
                "identity_state": (
                    "error"
                    if any(
                        issue["severity"] == "error"
                        for issue in identity_check["issues_by_tenant"].get(row.id, [])
                    )
                    else "warning"
                    if identity_check["issues_by_tenant"].get(row.id, [])
                    else "ok"
                ),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "modules": by_tenant.get(row.id, []),
            }
            for row in tenants
        ]
    }


async def _list_sem_identity_repair_candidates(session: AsyncSession) -> dict:
    """Report conservative duplicate-customer candidates without changing data."""
    await _start_sem_identity_read_transaction(session)
    tenants = list((await session.scalars(select(Tenant).order_by(Tenant.id))).all())
    modules = list(
        (await session.scalars(select(TenantModule).order_by(TenantModule.id))).all()
    )
    accounts = list(
        (
            await session.scalars(
                _sem_identity_account_select().order_by(BaiduAccount.id)
            )
        ).all()
    )
    oauth_grant_tenant_ids = {
        int(tenant_id)
        for tenant_id in (
            await session.scalars(
                select(BaiduOAuthGrant.tenant_id)
                .where(BaiduOAuthGrant.status == "active")
                .distinct()
            )
        ).all()
    }
    eligible_tenant_ids = _sem_identity_candidate_tenant_ids(
        tenants, modules, accounts, oauth_grant_tenant_ids
    )
    eligible_tenants = [
        tenant for tenant in tenants if tenant.id in eligible_tenant_ids
    ]
    eligible_accounts = [
        account for account in accounts if account.tenant_id in eligible_tenant_ids
    ]
    groups = _sem_duplicate_candidate_groups(eligible_tenants, eligible_accounts)
    return {
        "mode": "read_only_detection",
        "groups": groups,
        "summary": {
            "checked_customers": len(eligible_tenants),
            "candidate_groups": len(groups),
            "candidate_customers": sum(len(group["customers"]) for group in groups),
        },
        "safety": {
            "read_only": True,
            "writes_performed": 0,
            "execution_endpoint_available": False,
            "migration": "not-run",
        },
    }


@router.get(
    "/api/v1/admin/customers/sem-identity-repair/candidates",
    dependencies=[Depends(require_customer_admin)],
)
async def list_sem_identity_repair_candidates(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(_get_sem_identity_snapshot_session),
) -> dict:
    _set_sem_identity_repair_no_store(response)
    return await _run_sem_identity_repair_diagnostic(
        lambda: _list_sem_identity_repair_candidates(session), request=request
    )


async def _preview_sem_identity_repair(
    source_tenant_id: int,
    target_tenant_id: int,
    session: AsyncSession,
) -> dict:
    """Preview SEM ownership reassignment; no write or execution route exists."""
    if source_tenant_id == target_tenant_id:
        raise HTTPException(400, "来源客户和保留客户不能相同")
    await _start_sem_identity_read_transaction(session)
    source = await session.get(Tenant, source_tenant_id)
    target = await session.get(Tenant, target_tenant_id)
    if source is None or target is None:
        raise HTTPException(404, "来源客户或保留客户不存在")
    tenant_ids = (source_tenant_id, target_tenant_id)
    modules = list(
        (
            await session.scalars(
                select(TenantModule).where(TenantModule.tenant_id.in_(tenant_ids))
            )
        ).all()
    )
    accounts = list(
        (
            await session.scalars(
                _sem_identity_account_select()
                .where(BaiduAccount.tenant_id.in_(tenant_ids))
                .order_by(BaiduAccount.id)
            )
        ).all()
    )
    oauth_grant_tenant_ids = {
        int(tenant_id)
        for tenant_id in (
            await session.scalars(
                select(BaiduOAuthGrant.tenant_id)
                .where(BaiduOAuthGrant.tenant_id.in_(tenant_ids))
                .where(BaiduOAuthGrant.status == "active")
                .distinct()
            )
        ).all()
    }
    eligible_tenant_ids = _sem_identity_candidate_tenant_ids(
        [source, target], modules, accounts, oauth_grant_tenant_ids
    )
    if not set(tenant_ids).issubset(eligible_tenant_ids):
        raise HTTPException(400, "只允许预演具有明确 SEM 资格或账户证据的客户")
    row_counts = await _sem_identity_repair_row_counts(session, tenant_ids)
    return _sem_identity_repair_preview_payload(
        source,
        target,
        accounts,
        row_counts,
        active_oauth_grant_tenant_ids=oauth_grant_tenant_ids,
    )


@router.get(
    "/api/v1/admin/customers/sem-identity-repair/preview",
    dependencies=[Depends(require_customer_admin)],
)
async def preview_sem_identity_repair(
    request: Request,
    response: Response,
    source_tenant_id: int = Query(..., gt=0),
    target_tenant_id: int = Query(..., gt=0),
    session: AsyncSession = Depends(_get_sem_identity_snapshot_session),
) -> dict:
    _set_sem_identity_repair_no_store(response)
    return await _run_sem_identity_repair_diagnostic(
        lambda: _preview_sem_identity_repair(
            source_tenant_id, target_tenant_id, session
        ),
        request=request,
    )


@router.post("/api/v1/admin/customers", dependencies=[Depends(require_customer_admin)])
async def create_customer(req: CustomerCreate, session: AsyncSession = Depends(get_session)) -> dict:
    codes = {normalize_module_code(code) for code in req.modules}
    row = Tenant(
        name=req.name.strip(),
        industry=(req.industry or "").strip() or None,
        business_desc=(req.business_desc or "").strip() or None,
    )
    session.add(row)
    await session.flush()
    for code in sorted(codes):
        session.add(TenantModule(tenant_id=row.id, module_code=code, status="active"))
    await session.commit()
    await session.refresh(row)
    return {"status": "ok", "id": row.id}


@router.patch("/api/v1/admin/customers/{tenant_id}")
async def update_customer(
    tenant_id: int,
    req: CustomerUpdate,
    ctx: AuthContext = Depends(require_customer_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = await session.get(Tenant, tenant_id)
    if row is None:
        raise HTTPException(404, "客户不存在")
    values = req.model_dump(exclude_unset=True)
    confirm_name_change = bool(values.pop("confirm_bound_name_change", False))
    name_change_reason = str(values.pop("name_change_reason", "") or "").strip()
    name_change_audit: dict | None = None
    if "name" in values:
        new_name = str(values["name"] or "").strip()
        if not new_name:
            raise HTTPException(422, "客户名称不能为空")
        if new_name != row.name:
            linked_accounts = list(
                (
                    await session.scalars(
                        select(BaiduAccount)
                        .where(BaiduAccount.tenant_id == tenant_id)
                        .order_by(BaiduAccount.id)
                    )
                ).all()
            )
            if linked_accounts and (
                not confirm_name_change or len(name_change_reason) < 4
            ):
                raise HTTPException(
                    409,
                    "该客户已绑定百度推广账户。更名必须填写至少 4 个字的原因并完成二次确认；"
                    "如账户归属错误，请走人工审核的数据迁移流程，不能用更名代替迁移。",
                )
            if linked_accounts:
                name_change_audit = {
                    "old_name": row.name,
                    "new_name": new_name,
                    "reason": name_change_reason,
                    "account_ids": [account.id for account in linked_accounts],
                    "account_ucids": [str(account.baidu_ucid) for account in linked_accounts],
                }
        values["name"] = new_name
    for key, value in values.items():
        setattr(row, key, value.strip() or None if isinstance(value, str) else value)
    await session.commit()
    if name_change_audit:
        logger.warning(
            "AUDIT customer_bound_name_changed actor_user_id=%r actor_username=%r "
            "tenant_id=%r old_name=%r new_name=%r reason=%r account_ids=%r account_ucids=%r",
            ctx.user_id,
            ctx.username,
            tenant_id,
            name_change_audit["old_name"],
            name_change_audit["new_name"],
            name_change_audit["reason"],
            name_change_audit["account_ids"],
            name_change_audit["account_ucids"],
        )
    return {"status": "ok"}


@router.put(
    "/api/v1/admin/customers/{tenant_id}/modules/{module_code}",
    dependencies=[Depends(require_customer_admin)],
)
async def set_customer_module(
    tenant_id: int,
    module_code: str,
    req: ModuleUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict:
    if await session.get(Tenant, tenant_id) is None:
        raise HTTPException(404, "客户不存在")
    code = normalize_module_code(module_code)
    row = await session.scalar(
        select(TenantModule).where(
            TenantModule.tenant_id == tenant_id,
            TenantModule.module_code == code,
        )
    )
    if row is None:
        row = TenantModule(tenant_id=tenant_id, module_code=code)
        session.add(row)
    row.status = req.status
    row.expires_at = req.expires_at
    await session.commit()
    await session.refresh(row)
    return {"status": "ok", "module": _module_payload(row)}


@router.post(
    "/api/v1/admin/customers/{tenant_id}/sem-accounts/{account_id}/archive",
    dependencies=[Depends(require_customer_admin)],
)
async def archive_sem_account(
    tenant_id: int,
    account_id: int,
    req: SemAccountArchive,
    ctx: AuthContext = Depends(require_customer_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """归档一条错误/过期的百度推广账户绑定。

    仅软删除（status -> archived），不物理删除记录：campaigns/keywords/
    writeback_actions 等历史数据通过外键引用 baidu_accounts，物理删除会破坏
    审计与结算历史。归档后账户不再出现在客户可见的账户列表和 SEM 归属校验里，
    但记录本身连同其历史关联数据保留、可追溯。
    """
    row = await session.scalar(
        select(BaiduAccount)
        .where(BaiduAccount.id == account_id)
        .with_for_update()
    )
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "推广账户不存在")
    if row.status == "archived":
        raise HTTPException(409, "该账户绑定已经归档")
    old_status = row.status
    old_ucid = row.baidu_ucid
    reason = req.reason.strip()
    row.status = "archived"
    await session.commit()
    logger.warning(
        "AUDIT sem_account_archived actor_user_id=%r actor_username=%r "
        "tenant_id=%r account_id=%r ucid=%r old_status=%r reason=%r",
        ctx.user_id,
        ctx.username,
        tenant_id,
        account_id,
        str(old_ucid),
        old_status,
        reason,
    )
    return {"status": "ok"}


@router.get("/api/v1/sem/assets/accounts", dependencies=[Depends(require_scoped_auth)])
async def list_sem_accounts(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await ensure_module_access(session, ctx, tenant_id, "sem")
    rows = list(
        (
            await session.scalars(
                select(BaiduAccount)
                .where(
                    BaiduAccount.tenant_id == tenant_id,
                    BaiduAccount.status != "archived",
                )
                .order_by(BaiduAccount.id)
            )
        ).all()
    )
    async def asset_stats(model, synced_column) -> dict[int, dict]:
        result = await session.execute(
            select(
                model.baidu_account_id,
                func.count(),
                func.max(synced_column),
            )
            .where(model.tenant_id == tenant_id)
            .group_by(model.baidu_account_id)
        )
        return {
            account_id: {"count": int(count or 0), "last_synced_at": synced_at}
            for account_id, count, synced_at in result.all()
            if account_id is not None
        }

    campaign_stats = await asset_stats(Campaign, Campaign.synced_at)
    adgroup_stats = await asset_stats(Adgroup, Adgroup.synced_at)
    keyword_stats = await asset_stats(Keyword, Keyword.synced_at)
    search_term_stats = await asset_stats(SearchTermReport, SearchTermReport.synced_at)

    def account_payload(row: BaiduAccount) -> dict:
        counts = {
            "campaigns": campaign_stats.get(row.id, {}).get("count", 0),
            "adgroups": adgroup_stats.get(row.id, {}).get("count", 0),
            "keywords": keyword_stats.get(row.id, {}).get("count", 0),
            "search_terms": search_term_stats.get(row.id, {}).get("count", 0),
        }
        if row.status != "active":
            data_state = "inactive"
        elif row.sync_status == "failed":
            data_state = "failed"
        elif row.sync_status == "partial":
            data_state = "partial"
        elif row.sync_status in {"pending", "syncing"}:
            data_state = row.sync_status
        elif not row.last_synced_at:
            data_state = "not_synced"
        elif counts["campaigns"] and (not counts["adgroups"] or not counts["keywords"]):
            data_state = "partial"
        elif not any(counts.values()):
            data_state = "empty"
        else:
            data_state = "ready"
        latest_asset_sync = max(
            (
                item.get("last_synced_at")
                for item in (
                    campaign_stats.get(row.id, {}),
                    adgroup_stats.get(row.id, {}),
                    keyword_stats.get(row.id, {}),
                    search_term_stats.get(row.id, {}),
                )
                if item.get("last_synced_at") is not None
            ),
            default=None,
        )
        persisted_dimensions = (
            (row.asset_sync_state or {}).get("dimensions", {})
            if isinstance(row.asset_sync_state, dict)
            else {}
        )
        dimensions = {}
        for name in ("campaigns", "adgroups", "keywords", "search_terms"):
            detail = dict(persisted_dimensions.get(name) or {})
            if detail.get("error"):
                detail["error"] = public_sync_error(detail["error"])
            detail["count"] = counts[name]
            if not detail.get("status"):
                detail["status"] = "success" if counts[name] else "not_synced"
            dimensions[name] = detail
        return {
            "id": row.id,
            "platform": "baidu",
            "account_name": row.baidu_username,
            "external_account_id": str(row.baidu_ucid),
            "auth_mode": row.auth_mode,
            "status": row.status,
            "sync_status": row.sync_status,
            "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
            "last_asset_synced_at": latest_asset_sync.isoformat() if latest_asset_sync else None,
            "last_sync_error": public_sync_error(row.last_sync_error),
            "data_state": data_state,
            "counts": counts,
            "dimensions": dimensions,
        }

    accounts = [account_payload(row) for row in rows]
    return {
        "accounts": [
            account for account in accounts
        ],
        "summary": {
            "total": len(accounts),
            "active": sum(account["status"] == "active" for account in accounts),
            "ready": sum(account["data_state"] == "ready" for account in accounts),
            "attention": sum(
                account["data_state"] in {"failed", "not_synced", "partial", "empty"}
                for account in accounts
            ),
        },
        "connect_path": "/onboarding",
    }


@router.post(
    "/api/v1/sem/assets/accounts/{account_id}/repair-sync",
    dependencies=[Depends(require_scoped_auth)],
)
async def repair_sem_account_assets(
    account_id: int,
    tenant_id: int = Query(...),
    dimension: str | None = Query(None),
    history_days: int | None = Query(None, ge=2, le=90),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """只读补偿同步：只从百度拉取资产，不执行任何百度写回。"""
    await ensure_module_access(session, ctx, tenant_id, "sem")
    if not ctx.can_edit("onboarding"):
        raise HTTPException(403, "需要首次接入编辑权限才能发起补偿同步")
    account = await session.get(BaiduAccount, account_id)
    if account is None or account.tenant_id != tenant_id:
        raise HTTPException(404, "推广账户不存在")
    if account.status != "active":
        raise HTTPException(409, "账户未生效，无法同步")
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "客户不存在")
    if history_days is not None and dimension not in (None, "reports"):
        raise HTTPException(422, "历史回填仅支持关键词报告维度")

    # 延迟导入避免 API 路由加载时与 scheduler 形成循环依赖。
    from app.scheduler import refresh_keyword_workbench_snapshot

    try:
        today = datetime.now().date()
        result = await refresh_keyword_workbench_snapshot(
            session,
            tenant,
            account,
            today,
            dimensions=[dimension] if dimension else None,
            report_start_date=(
                today - timedelta(days=history_days - 1)
                if history_days is not None
                else None
            ),
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result.get("status") == "busy":
        raise HTTPException(409, "该客户正在同步，请稍后刷新状态")
    return {"status": "ok", "mode": "read_only_repair", "result": result}


class SeoSiteCreate(BaseModel):
    tenant_id: int
    name: str = Field(min_length=1, max_length=120)
    domain: str = Field(min_length=3, max_length=255)


class SeoSiteUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    domain: str | None = Field(None, min_length=3, max_length=255)
    status: str | None = Field(None, pattern="^(active|paused|archived)$")


def _site_payload(row: SeoSite) -> dict:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "name": row.name,
        "domain": row.domain,
        "canonical_domain": row.canonical_domain,
        "default_url": row.default_url,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _require_seo_asset_permission(ctx: AuthContext, *, edit: bool = False) -> None:
    allowed = ctx.can_edit("seo.assets") if edit else ctx.can_view("seo.assets")
    if not allowed:
        raise HTTPException(403, "当前账号没有 SEO 网站管理权限")


_SEO_SITE_DEPENDENCIES = (
    (SeoKeywordAsset, "关键词"),
    (SeoRankSnapshot, "排名快照"),
    (SeoSerpResult, "SERP 结果"),
    (SeoBrandAsset, "品牌资产"),
    (SeoSitePage, "站内页面"),
    (SeoContentAsset, "内容资产"),
    (SeoInternalLink, "内链"),
    (SeoBacklink, "外链"),
    (SeoCompetitor, "竞品"),
    (SeoCompetitorEvent, "竞品动态"),
    (SeoCrawlRun, "抓取任务"),
    (SeoPageSnapshot, "页面抓取快照"),
    (SeoMetricSnapshot, "网站指标快照"),
)


async def _seo_site_delete_blockers(
    session: AsyncSession, *, tenant_id: int, site_id: int
) -> dict[str, int]:
    blockers: dict[str, int] = {}
    for model, label in _SEO_SITE_DEPENDENCIES:
        count = int(
            await session.scalar(
                select(func.count()).select_from(model).where(
                    model.tenant_id == tenant_id,
                    model.site_id == site_id,
                )
            )
            or 0
        )
        if count:
            blockers[label] = count
    return blockers


@seo_sites_router.get("/api/v1/seo/sites", dependencies=[Depends(require_scoped_auth)])
async def list_seo_sites(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _require_seo_asset_permission(ctx)
    await ensure_module_access(session, ctx, tenant_id, "seo")
    rows = list((await session.scalars(select(SeoSite).where(SeoSite.tenant_id == tenant_id).order_by(SeoSite.id))).all())
    return {"sites": [_site_payload(row) for row in rows]}


@seo_sites_router.post("/api/v1/seo/sites", dependencies=[Depends(require_scoped_auth)])
async def create_seo_site(
    req: SeoSiteCreate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _require_seo_asset_permission(ctx, edit=True)
    module = await ensure_module_access(session, ctx, req.tenant_id, "seo")
    canonical, default_url = _canonical_domain(req.domain)
    row = SeoSite(
        tenant_id=req.tenant_id,
        tenant_module_id=module.id,
        name=req.name.strip(),
        domain=req.domain.strip(),
        canonical_domain=canonical,
        default_url=default_url,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "该客户已经维护了这个 SEO 网站") from exc
    await session.refresh(row)
    return _site_payload(row)


@seo_sites_router.patch("/api/v1/seo/sites/{site_id}", dependencies=[Depends(require_scoped_auth)])
async def update_seo_site(
    site_id: int,
    tenant_id: int,
    req: SeoSiteUpdate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _require_seo_asset_permission(ctx, edit=True)
    await ensure_module_access(session, ctx, tenant_id, "seo")
    row = await session.get(SeoSite, site_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "SEO 网站不存在")
    if req.name is not None:
        row.name = req.name.strip()
    if req.domain is not None:
        canonical, default_url = _canonical_domain(req.domain)
        row.domain = req.domain.strip()
        row.canonical_domain = canonical
        row.default_url = default_url
    if req.status is not None:
        row.status = req.status
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "该客户已经维护了这个 SEO 网站") from exc
    await session.refresh(row)
    return _site_payload(row)


@seo_sites_router.delete("/api/v1/seo/sites/{site_id}", dependencies=[Depends(require_scoped_auth)])
async def delete_seo_site(
    site_id: int,
    tenant_id: int,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Delete only an empty SEO site; populated sites must be archived instead."""
    _require_seo_asset_permission(ctx, edit=True)
    await ensure_module_access(session, ctx, tenant_id, "seo")
    row = await session.get(SeoSite, site_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "SEO 网站不存在")
    blockers = await _seo_site_delete_blockers(
        session, tenant_id=tenant_id, site_id=site_id
    )
    if blockers:
        summary = "、".join(f"{label} {count} 条" for label, count in blockers.items())
        raise HTTPException(
            409,
            f"该网站已有 SEO 数据（{summary}），不能直接删除；请将状态改为归档。",
        )
    await session.delete(row)
    await session.commit()
    return {"deleted": True, "site_id": site_id}


router.include_router(seo_sites_router)


class GeoProjectCreate(BaseModel):
    tenant_id: int
    name: str = Field(min_length=1, max_length=120)
    brand_name: str | None = Field(None, max_length=160)
    domain: str = Field(min_length=3, max_length=255)
    description: str | None = Field(None, max_length=4000)


class GeoProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    brand_name: str | None = Field(None, max_length=160)
    domain: str | None = Field(None, min_length=3, max_length=255)
    description: str | None = Field(None, max_length=4000)
    status: str | None = Field(None, pattern="^(active|paused|archived)$")


def _project_payload(row: GeoProject) -> dict:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "name": row.name,
        "brand_name": row.brand_name,
        "domain": row.primary_domain,
        "canonical_domain": row.canonical_domain,
        "default_url": row.default_url,
        "description": row.description,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@geo_projects_router.get("/api/v1/geo/projects", dependencies=[Depends(require_scoped_auth)])
async def list_geo_projects(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await ensure_module_access(session, ctx, tenant_id, "geo")
    rows = list((await session.scalars(select(GeoProject).where(GeoProject.tenant_id == tenant_id).order_by(GeoProject.id))).all())
    return {"projects": [_project_payload(row) for row in rows]}


@geo_projects_router.post("/api/v1/geo/projects", dependencies=[Depends(require_scoped_auth)])
async def create_geo_project(
    req: GeoProjectCreate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    module = await ensure_module_access(session, ctx, req.tenant_id, "geo")
    canonical, default_url = _canonical_domain(req.domain)
    row = GeoProject(
        tenant_id=req.tenant_id,
        tenant_module_id=module.id,
        name=req.name.strip(),
        brand_name=(req.brand_name or "").strip() or None,
        primary_domain=req.domain.strip(),
        canonical_domain=canonical,
        default_url=default_url,
        description=(req.description or "").strip() or None,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "该客户已经维护了这个 GEO 项目网站") from exc
    await session.refresh(row)
    return _project_payload(row)


@geo_projects_router.patch("/api/v1/geo/projects/{project_id}", dependencies=[Depends(require_scoped_auth)])
async def update_geo_project(
    project_id: int,
    tenant_id: int,
    req: GeoProjectUpdate,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await ensure_module_access(session, ctx, tenant_id, "geo")
    row = await session.get(GeoProject, project_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "GEO 项目不存在")
    values = req.model_dump(exclude_unset=True)
    if "domain" in values:
        canonical, default_url = _canonical_domain(values.pop("domain"))
        row.primary_domain = req.domain.strip()
        row.canonical_domain = canonical
        row.default_url = default_url
    for key, value in values.items():
        setattr(row, key, value.strip() or None if isinstance(value, str) else value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "该客户已经维护了这个 GEO 项目网站") from exc
    await session.refresh(row)
    return _project_payload(row)
