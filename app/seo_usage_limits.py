"""Atomic tenant-level daily usage limits stored in the SEO module workspace."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.module_workspace import TenantModule


SEO_USAGE_KEY = "seo_daily_usage"
SEO_USAGE_TIMEZONE = ZoneInfo("Asia/Shanghai")


class SeoUsageLimitError(RuntimeError):
    def __init__(self, resource: str, used: int, limit: int) -> None:
        super().__init__(f"{resource} 当日配额已用完")
        self.resource = resource
        self.used = used
        self.limit = limit


async def charge_seo_usage(
    session: AsyncSession,
    tenant_id: int,
    resource: str,
    amount: int,
    limit: int,
) -> dict[str, int | str]:
    amount = max(1, int(amount))
    limit = max(1, int(limit))
    module = await session.scalar(
        select(TenantModule)
        .where(
            TenantModule.tenant_id == tenant_id,
            TenantModule.module_code == "seo",
        )
        .with_for_update()
    )
    if module is None:
        raise SeoUsageLimitError(resource, limit, limit)
    settings = dict(module.module_settings or {})
    usage = dict(settings.get(SEO_USAGE_KEY) or {})
    today = datetime.now(SEO_USAGE_TIMEZONE).date().isoformat()
    if usage.get("date") != today:
        usage = {"date": today}
    used = max(0, int(usage.get(resource) or 0))
    if used + amount > limit:
        await session.rollback()
        raise SeoUsageLimitError(resource, used, limit)
    usage[resource] = used + amount
    settings[SEO_USAGE_KEY] = usage
    module.module_settings = settings
    await session.commit()
    return {"date": today, "used": used + amount, "limit": limit}


async def refund_seo_usage(
    session: AsyncSession,
    tenant_id: int,
    resource: str,
    amount: int,
) -> None:
    module = await session.scalar(
        select(TenantModule)
        .where(
            TenantModule.tenant_id == tenant_id,
            TenantModule.module_code == "seo",
        )
        .with_for_update()
    )
    if module is None:
        await session.rollback()
        return
    settings = dict(module.module_settings or {})
    usage = dict(settings.get(SEO_USAGE_KEY) or {})
    today = datetime.now(SEO_USAGE_TIMEZONE).date().isoformat()
    if usage.get("date") == today:
        usage[resource] = max(0, int(usage.get(resource) or 0) - max(1, int(amount)))
        settings[SEO_USAGE_KEY] = usage
        module.module_settings = settings
        await session.commit()
    else:
        await session.rollback()
