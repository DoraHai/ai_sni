"""调价回写台账查询接口（只读）。

回写动作本身在 keywords.py 的 POST /{id}/writeback（归 optimize.keywords edit）；
本模块只查台账，归 verify.adjustments view（与调价台账同组「效果验证」）。
"""
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import WRITEBACK_STATUS_LABELS, BidWriteback
from app.security.auth import require_scoped_auth

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/writeback",
    tags=["调价回写台账"],
    dependencies=[Depends(require_scoped_auth)],
)


def wb_to_dict(r: BidWriteback) -> dict:
    return {
        "id": r.id,
        "suggestion_id": r.suggestion_id,
        "keyword_id": r.keyword_id,
        "keyword": r.keyword,
        "campaign_id": r.campaign_id,
        "campaign_name": r.campaign_name,
        "adgroup_id": r.adgroup_id,
        "old_bid": float(r.old_bid) if r.old_bid is not None else None,
        "new_bid": float(r.new_bid),
        "change_pct": float(r.change_pct) if r.change_pct is not None else None,
        "dry_run": r.dry_run,
        "status": r.status,
        "status_label": WRITEBACK_STATUS_LABELS.get(r.status, r.status),
        "error_msg": r.error_msg,
        "operator_name": r.operator_name,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "executed_at": r.executed_at.isoformat() if r.executed_at else None,
    }


@router.get("")
async def list_writebacks(
    tenant_id: int = Query(..., description="本地租户 ID"),
    status: str | None = Query(None, description="success/failed/dry_run，传 all 或空看全部"),
    limit: int = Query(200, le=500),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """回写台账列表（按时间倒序）+ 按状态计数。"""
    cond = [BidWriteback.tenant_id == tenant_id]
    if status and status != "all":
        cond.append(BidWriteback.status == status)

    rows = (
        await session.scalars(
            select(BidWriteback)
            .where(*cond)
            .order_by(BidWriteback.id.desc())
            .limit(limit)
        )
    ).all()

    count_rows = (
        await session.execute(
            select(BidWriteback.status, func.count())
            .where(BidWriteback.tenant_id == tenant_id)
            .group_by(BidWriteback.status)
        )
    ).all()

    return {
        "status_counts": {s: int(n) for s, n in count_rows},
        "writebacks": [wb_to_dict(r) for r in rows],
    }
