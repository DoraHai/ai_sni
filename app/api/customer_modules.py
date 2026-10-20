from __future__ import annotations

from datetime import date, timedelta, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import BaiduAccount, GeoProject, SeoSite, Tenant, TenantModule
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
    SeoSiteAdvisorAssignment,
)
from app.module_scope import (
    MODULE_CODES,
    ensure_module_access,
    get_tenant_module,
    module_is_available,
    normalize_module_code,
)
from app.security.auth import AuthContext, require_auth, require_scoped_auth
from app.seo_demo_source import (
    get_seo_session,
    require_seo_auth,
    require_seo_scoped_auth,
)


router = APIRouter(tags=["客户与模块"])
seo_sites_router = APIRouter(tags=["SEO 网站"])
geo_projects_router = APIRouter(tags=["GEO 项目"])


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


class CustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    industry: str | None = Field(None, max_length=100)
    business_desc: str | None = Field(None, max_length=4000)
    modules: list[str] = Field(default_factory=lambda: ["sem"])


class CustomerUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    industry: str | None = Field(None, max_length=100)
    business_desc: str | None = Field(None, max_length=4000)


class ModuleUpdate(BaseModel):
    status: str = Field(pattern="^(active|trial|suspended|closed)$")
    expires_at: date | None = None


@router.get("/api/v1/admin/customers", dependencies=[Depends(require_customer_admin)])
async def list_customers(session: AsyncSession = Depends(get_session)) -> dict:
    tenants = list((await session.scalars(select(Tenant).order_by(Tenant.id))).all())
    modules = list((await session.scalars(select(TenantModule).order_by(TenantModule.id))).all())
    by_tenant: dict[int, list[dict]] = {}
    for row in modules:
        by_tenant.setdefault(row.tenant_id, []).append(_module_payload(row))
    return {
        "customers": [
            {
                "id": row.id,
                "name": row.name,
                "industry": row.industry,
                "business_desc": row.business_desc,
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


@router.patch("/api/v1/admin/customers/{tenant_id}", dependencies=[Depends(require_customer_admin)])
async def update_customer(
    tenant_id: int,
    req: CustomerUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict:
    row = await session.get(Tenant, tenant_id)
    if row is None:
        raise HTTPException(404, "客户不存在")
    values = req.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(row, key, value.strip() or None if isinstance(value, str) else value)
    await session.commit()
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
                .where(BaiduAccount.tenant_id == tenant_id)
                .order_by(BaiduAccount.id)
            )
        ).all()
    )
    return {
        "accounts": [
            {
                "id": row.id,
                "platform": "baidu",
                "account_name": row.baidu_username,
                "external_account_id": str(row.baidu_ucid),
                "status": row.status,
                "sync_status": row.sync_status,
                "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
            }
            for row in rows
        ],
        "connect_path": "/onboarding",
    }


class SeoSiteCreate(BaseModel):
    tenant_id: int
    name: str = Field(min_length=1, max_length=120)
    domain: str = Field(min_length=3, max_length=255)


class SeoSiteUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    domain: str | None = Field(None, min_length=3, max_length=255)
    status: str | None = Field(None, pattern="^(active|paused)$")


def _site_payload(row: SeoSite) -> dict:
    created_at = row.created_at
    if created_at is not None and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone(timedelta(hours=8)))
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "name": row.name,
        "domain": row.domain,
        "canonical_domain": row.canonical_domain,
        "default_url": row.default_url,
        "status": row.status,
        "created_at": created_at.isoformat() if created_at else None,
    }


def _require_seo_asset_permission(ctx: AuthContext, *, edit: bool = False) -> None:
    allowed = ctx.can_edit("seo.assets") if edit else ctx.can_view("seo.assets")
    if not allowed:
        raise HTTPException(403, "当前账号没有 SEO 网站管理权限")


def _require_seo_workbench_site_permission(ctx: AuthContext) -> None:
    if not ctx.can_view("seo.content", "seo.site"):
        raise HTTPException(403, "当前账号没有 SEO 内容或页面查看权限")


@seo_sites_router.get("/api/v1/seo/sites", dependencies=[Depends(require_seo_auth)])
async def list_seo_sites(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_seo_auth),
    session: AsyncSession = Depends(get_seo_session),
) -> dict:
    _require_seo_asset_permission(ctx)
    await ensure_module_access(session, ctx, tenant_id, "seo")
    rows = list((await session.scalars(select(SeoSite).where(SeoSite.tenant_id == tenant_id).order_by(SeoSite.id))).all())
    return {"sites": [_site_payload(row) for row in rows]}


@seo_sites_router.get(
    "/api/v1/seo/workbench/sites",
    dependencies=[Depends(require_seo_scoped_auth)],
)
async def list_seo_workbench_sites(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_seo_scoped_auth),
    session: AsyncSession = Depends(get_seo_session),
) -> dict:
    """Return the stored SEO site scope without starting any background work."""
    _require_seo_workbench_site_permission(ctx)
    await ensure_module_access(session, ctx, tenant_id, "seo")
    rows = list(
        (
            await session.scalars(
                select(SeoSite)
                .where(SeoSite.tenant_id == tenant_id)
                .order_by(SeoSite.id)
            )
        ).all()
    )
    return {
        "tenant_id": tenant_id,
        "selection_policy": {
            "selectable_statuses": ["active"],
            "disabled_statuses": ["paused", "archived"],
        },
        "sites": [
            {
                "id": row.id,
                "name": row.name,
                "domain": row.domain,
                "status": row.status,
            }
            for row in rows
        ],
    }


@seo_sites_router.post("/api/v1/seo/sites", dependencies=[Depends(require_seo_auth)])
async def create_seo_site(
    req: SeoSiteCreate,
    ctx: AuthContext = Depends(require_seo_auth),
    session: AsyncSession = Depends(get_seo_session),
) -> dict:
    _require_seo_asset_permission(ctx, edit=True)
    from app.security.advisor_write_routes import check_advisor_handler
    check_advisor_handler(ctx, "POST", "/sites", req.model_dump())
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
    assignment = None
    try:
        if ctx.is_advisor:
            # The site is new: its unique tenant/domain insert must succeed
            # before assigning it. A duplicate request never reaches this step
            # and cannot claim an existing site or duplicate its assignment.
            await session.flush()
            assignment = SeoSiteAdvisorAssignment(
                tenant_id=row.tenant_id,
                site_id=row.id,
                advisor_user_id=ctx.user_id,
                active=True,
                assigned_by=ctx.user_id,
            )
            session.add(assignment)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "该客户已经维护了这个 SEO 网站") from exc
    except Exception:
        # Includes a rejected commit-time grant check or assignment insert.
        await session.rollback()
        raise
    if assignment is not None:
        from app.security.advisor_write_commit import record_seo_action
        # Use the existing metadata-only operation log after a successful
        # commit; failed transactions must never emit a successful assignment.
        record_seo_action(ctx, row.tenant_id, "POST", "/api/v1/seo/sites",
                          assignment.__tablename__, [assignment.id])
    # Avoid an unnecessary filtered reload in the advisor request session.
    if not getattr(ctx, "is_advisor", False):
        await session.refresh(row)
    return _site_payload(row)


@seo_sites_router.patch("/api/v1/seo/sites/{site_id}", dependencies=[Depends(require_seo_auth)])
async def update_seo_site(
    site_id: int,
    tenant_id: int,
    req: SeoSiteUpdate,
    ctx: AuthContext = Depends(require_seo_auth),
    session: AsyncSession = Depends(get_seo_session),
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
    # A just-paused advisor site is intentionally absent from subsequent
    # active-site reads. Return the already saved object without reloading it.
    if not getattr(ctx, 'is_advisor', False):
        await session.refresh(row)
    return _site_payload(row)


@seo_sites_router.delete("/api/v1/seo/sites/{site_id}", dependencies=[Depends(require_seo_auth)])
async def delete_seo_site(
    site_id: int,
    tenant_id: int,
    confirm_domain: str = Query(..., min_length=3),
    ctx: AuthContext = Depends(require_seo_auth),
    session: AsyncSession = Depends(get_seo_session),
) -> dict:
    """Delete this website and its SEO records in one transaction after confirmation."""
    _require_seo_asset_permission(ctx, edit=True)
    ctx.ensure_tenant(tenant_id)
    await ensure_module_access(session, ctx, tenant_id, "seo")
    row = await session.scalar(select(SeoSite).where(
        SeoSite.id == site_id, SeoSite.tenant_id == tenant_id,
    ).with_for_update())
    if row is None:
        raise HTTPException(404, "SEO 网站不存在")
    if not isinstance(confirm_domain, str) or confirm_domain != row.canonical_domain:
        raise HTTPException(409, "网站域名已变化，请刷新后重新确认删除")
    # Never allow an old database to SET NULL child rows and leave orphaned assets.
    ready = await session.scalar(text("""
        SELECT EXISTS (SELECT 1 FROM pg_trigger
          WHERE tgrelid=to_regclass('seo_sites') AND tgname='trg_seo_site_purge'
            AND tgenabled='O' AND NOT tgisinternal)
    """))
    if not ready:
        raise HTTPException(503, "网站彻底删除功能尚未完成数据库升级")
    try:
        await session.delete(row)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "删除未完成，所有数据已保留，请稍后重试") from exc
    return {"deleted": True, "site_id": site_id}


# Keep the shared backend's existing route surface while allowing the
# independent SEO service to mount only SEO website management endpoints.
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
