"""AI 每日洞察接口（盯盘页）。

生成见 app/ai/insight.py。按天缓存，首次访问当天 lazy 生成；force=true 强制重算。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.insight import generate_insight
from app.database import get_session
from app.models import Tenant
from app.security.auth import require_scoped_auth

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/dashboard",
    tags=["AI 每日洞察"],
    dependencies=[Depends(require_scoped_auth)],
)


@router.get("/insight")
async def get_insight(
    tenant_id: int = Query(..., description="本地租户 ID"),
    force: bool = Query(False, description="true=强制重新生成（忽略当天缓存）"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """取当天 AI 每日洞察。未配 DeepSeek 时 enabled=false（前端不显示洞察卡）。"""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在，请确认 tenant_id")
    ins = await generate_insight(session, tenant, force=force)
    if ins is None:
        return {"enabled": False}
    return {
        "enabled": True,
        "insight_date": ins.insight_date.isoformat(),
        "summary": ins.summary,
        "detail": ins.detail or {"highlights": [], "actions": []},
        "created_at": ins.created_at.isoformat() if ins.created_at else None,
    }
