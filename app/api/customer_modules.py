from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import (
    Adgroup,
    BaiduAccount,
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
    accounts = list((await session.scalars(select(BaiduAccount).order_by(BaiduAccount.id))).all())
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
