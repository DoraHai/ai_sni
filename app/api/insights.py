"""AI 每日洞察接口（盯盘页）。

生成见 app/ai/insight.py。按洞察日期缓存，首次访问 lazy 生成；force=true 强制重算。
"""
import logging
from datetime import date

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
    target_date: date | None = Query(
        None, description="洞察日期；看板传入所选区间的结束日期"
    ),
    force: bool = Query(False, description="true=强制重新生成（忽略当天缓存）"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """取所选结束日的 AI 洞察。未传日期时回退到最新数据日。"""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在，请确认 tenant_id")
    ins = await generate_insight(
        session, tenant, target_date=target_date, force=force
    )
    if ins is None:
        return {"enabled": False}
    return {
        "enabled": True,
        "insight_date": ins.insight_date.isoformat(),
        "summary": ins.summary,
        "detail": ins.detail or {"highlights": [], "actions": []},
        "created_at": ins.created_at.isoformat() if ins.created_at else None,
    }
