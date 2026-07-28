"""客户画像接口（每日盯盘 · 客户画像页）。menu = monitor.profile。

数据 6 维实时聚合（app/ai/customer_profile.py）；AI 总结缓存在 tenants。
行业/业务描述可编辑（喂调价建议 + 画像页）。🚫 只读聚合，不碰百度写回。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.customer_profile import gather_profile, generate_summary
from app.ai.deepseek import is_enabled as ai_enabled
from app.database import get_session
from app.models import Tenant
from app.security.auth import require_scoped_auth

router = APIRouter(
    prefix="/api/v1/customer-profile",
    tags=["客户画像"],
    dependencies=[Depends(require_scoped_auth)],
)


@router.get("")
async def get_profile(
    tenant_id: int = Query(..., description="本地租户 ID"),
    refresh_summary: bool = Query(False, description="true=强制重新生成 AI 总结"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在，请确认 tenant_id")
    profile = await gather_profile(session, tenant)
    summary = await generate_summary(session, tenant, profile, force=refresh_summary)
    return {
        "ai_enabled": ai_enabled(),
        "profile": profile,
        "summary": summary,
        "summary_generated_at": (
            tenant.profile_generated_at.isoformat() if tenant.profile_generated_at else None
        ),
    }


class UpdateProfileRequest(BaseModel):
    industry: str | None = Field(None, max_length=100)
    business_desc: str | None = Field(None, max_length=2000)


@router.patch("")
async def update_profile(
    tenant_id: int = Query(...),
    req: UpdateProfileRequest = ...,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """改行业/业务描述。改完清掉旧 AI 总结缓存（下次拉取按新描述重算）。"""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在，请确认 tenant_id")
    changed = False
    if req.industry is not None:
        tenant.industry = req.industry.strip() or None
        changed = True
    if req.business_desc is not None:
        tenant.business_desc = req.business_desc.strip() or None
        changed = True
    if changed:
        tenant.profile_summary = None  # 描述变了，旧总结作废
        tenant.profile_generated_at = None
    await session.commit()
    return {"status": "ok"}
