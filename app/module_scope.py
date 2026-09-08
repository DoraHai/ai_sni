from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    SeoContentAsset,
    SeoSite,
    Tenant,
    TenantModule,
)
from app.models.seo import SeoContentPublication
if TYPE_CHECKING:
    from app.security.auth import AuthContext


MODULE_CODES = {"sem", "seo", "geo"}
ACTIVE_MODULE_STATUSES = {"active", "trial"}


def normalize_module_code(value: str) -> str:
    code = str(value or "").strip().lower()
    if code not in MODULE_CODES:
        raise HTTPException(400, "模块必须是 sem、seo 或 geo")
    return code


def module_is_available(row: TenantModule) -> bool:
    return row.status in ACTIVE_MODULE_STATUSES and (
        row.expires_at is None or row.expires_at >= date.today()
    )


async def get_tenant_module(
    session: AsyncSession,
    tenant_id: int,
    module_code: str,
    *,
    require_active: bool = True,
) -> TenantModule:
    code = normalize_module_code(module_code)
    row = await session.scalar(
        select(TenantModule).where(
            TenantModule.tenant_id == tenant_id,
            TenantModule.module_code == code,
        )
    )
    if row is None:
        raise HTTPException(403, f"当前客户尚未开通 {code.upper()} 模块")
    if require_active and not module_is_available(row):
        raise HTTPException(403, f"当前客户的 {code.upper()} 模块未启用或已过期")
    return row


async def ensure_module_access(
    session: AsyncSession,
    ctx: "AuthContext",
    tenant_id: int,
    module_code: str,
) -> TenantModule:
    ctx.ensure_tenant(tenant_id)
    return await get_tenant_module(session, tenant_id, module_code)


async def list_active_module_tenants(
    session: AsyncSession,
    module_code: str,
) -> list[Tenant]:
    """Return tenants whose requested workspace is active and not expired."""
    code = normalize_module_code(module_code)
    stmt = (
        select(Tenant)
        .join(TenantModule, TenantModule.tenant_id == Tenant.id)
        .where(
            TenantModule.module_code == code,
            TenantModule.status.in_(ACTIVE_MODULE_STATUSES),
            or_(TenantModule.expires_at.is_(None), TenantModule.expires_at >= date.today()),
        )
        .order_by(Tenant.id)
    )
    return list((await session.scalars(stmt)).all())


async def seo_site_is_operational(
    session: AsyncSession,
    tenant_id: int,
    site_id: int,
) -> bool:
    """Return whether new SEO business work may start for this site."""
    today = date.today()
    return bool(
        await session.scalar(
            select(SeoSite.id)
            .join(
                TenantModule,
                and_(
                    TenantModule.id == SeoSite.tenant_module_id,
                    TenantModule.tenant_id == SeoSite.tenant_id,
                    TenantModule.module_code == "seo",
                ),
            )
            .where(
                SeoSite.id == site_id,
                SeoSite.tenant_id == tenant_id,
                SeoSite.status == "active",
                TenantModule.status.in_(ACTIVE_MODULE_STATUSES),
                or_(
                    TenantModule.expires_at.is_(None),
                    TenantModule.expires_at >= today,
                ),
            )
        )
    )


async def require_seo_site_operational(
    session: AsyncSession,
    tenant_id: int,
    site_id: int,
) -> None:
    """Reject new SEO business work for a paused/archived site or entitlement."""
    if not await seo_site_is_operational(session, tenant_id, site_id):
        raise HTTPException(409, "SEO 网站已暂停或归档，不能启动新的业务动作")


async def require_any_operational_seo_site(
    session: AsyncSession,
    tenant_id: int,
) -> None:
    """Require an operational site for tenant-wide SEO mutations."""
    today = date.today()
    site_id = await session.scalar(
        select(SeoSite.id)
        .join(
            TenantModule,
            and_(
                TenantModule.id == SeoSite.tenant_module_id,
                TenantModule.tenant_id == SeoSite.tenant_id,
                TenantModule.module_code == "seo",
            ),
        )
        .where(
            SeoSite.tenant_id == tenant_id,
            SeoSite.status == "active",
            TenantModule.status.in_(ACTIVE_MODULE_STATUSES),
            or_(
                TenantModule.expires_at.is_(None),
                TenantModule.expires_at >= today,
            ),
        )
        .limit(1)
    )
    if site_id is None:
        raise HTTPException(409, "当前客户没有可执行新业务动作的 SEO 网站")


async def seo_publication_site_is_operational(
    session: AsyncSession,
    tenant_id: int,
    publication_id: int,
) -> bool:
    """Re-read a durable publication's site immediately before provider writes."""
    site_id = await session.scalar(
        select(SeoContentAsset.site_id)
        .join(
            SeoContentPublication,
            SeoContentPublication.content_asset_id == SeoContentAsset.id,
        )
        .where(
            SeoContentPublication.id == publication_id,
            SeoContentPublication.tenant_id == tenant_id,
            SeoContentAsset.tenant_id == tenant_id,
        )
        .execution_options(populate_existing=True)
    )
    return site_id is not None and await seo_site_is_operational(
        session, tenant_id, int(site_id)
    )


async def list_module_tenants(
    session: AsyncSession,
    ctx: "AuthContext",
    module_code: str,
) -> list[Tenant]:
    code = normalize_module_code(module_code)
    stmt = (
        select(Tenant)
        .join(TenantModule, TenantModule.tenant_id == Tenant.id)
        .where(
            TenantModule.module_code == code,
            TenantModule.status.in_(ACTIVE_MODULE_STATUSES),
            or_(TenantModule.expires_at.is_(None), TenantModule.expires_at >= date.today()),
        )
        .order_by(Tenant.id)
    )
    if ctx.tenant_id is not None:
        stmt = stmt.where(Tenant.id == ctx.tenant_id)
    rows = list((await session.scalars(stmt)).all())
    return rows
