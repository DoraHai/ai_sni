"""调价回写台账查询接口（只读）。

回写动作本身在 keywords.py 的 POST /{id}/writeback（归 optimize.keywords edit）；
本模块只查台账，归 verify.adjustments view（与调价台账同组「效果验证」）。
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.baidu.writeback_approval import (
    ALLOWED_ACTIONS,
    WritebackApprovalError,
    payload_fingerprint,
)
from app.database import get_session
from app.models import WRITEBACK_STATUS_LABELS, BidWriteback, WritebackApproval
from app.security.auth import AuthContext, require_scoped_auth

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/writeback",
    tags=["调价回写台账"],
    dependencies=[Depends(require_scoped_auth)],
)


class ApprovalRequest(BaseModel):
    tenant_id: int
    action_type: str
    payload: dict
    note: str | None = Field(None, max_length=1000)


class ApprovalDecision(BaseModel):
    decision: str
    note: str | None = Field(None, max_length=1000)


def approval_to_dict(row: WritebackApproval) -> dict:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "action_type": row.action_type,
        "payload": row.payload,
        "status": row.status,
        "request_note": row.request_note,
        "decision_note": row.decision_note,
        "requested_by": row.requested_by,
        "approved_by": row.approved_by,
        "consumed_by": row.consumed_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "consumed_at": row.consumed_at.isoformat() if row.consumed_at else None,
    }


@router.post("/approvals")
async def request_writeback_approval(
    req: ApprovalRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """申请高风险资金回写；审批参数会被规范化并绑定指纹。"""
    ctx.ensure_tenant(req.tenant_id)
    if ctx.user_id is None:
        raise HTTPException(403, "审批申请必须使用实名登录账号")
    if req.action_type not in ALLOWED_ACTIONS:
        raise HTTPException(400, "该动作不属于需要资金审批的回写类型")
    try:
        normalized, fingerprint = payload_fingerprint(req.action_type, req.payload)
    except (KeyError, TypeError, ValueError, WritebackApprovalError) as exc:
        raise HTTPException(400, f"审批参数不合法：{exc}") from exc
    row = WritebackApproval(
        tenant_id=req.tenant_id,
        action_type=req.action_type,
        payload=normalized,
        payload_hash=fingerprint,
        status="pending",
        request_note=req.note,
        requested_by=ctx.user_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {"approval": approval_to_dict(row)}


@router.get("/approvals")
async def list_writeback_approvals(
    tenant_id: int = Query(...),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    cond = [WritebackApproval.tenant_id == tenant_id]
    if status and status != "all":
        cond.append(WritebackApproval.status == status)
    rows = (
        await session.scalars(
            select(WritebackApproval)
            .where(*cond)
            .order_by(WritebackApproval.id.desc())
            .limit(limit)
        )
    ).all()
    return {"approvals": [approval_to_dict(row) for row in rows]}


@router.post("/approvals/{approval_id}/decision")
async def decide_writeback_approval(
    approval_id: int,
    req: ApprovalDecision,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """审批或驳回；批准时强制审批人与申请人不同。"""
    if ctx.user_id is None:
        raise HTTPException(403, "审批操作必须使用实名登录账号")
    if req.decision not in {"approved", "rejected"}:
        raise HTTPException(400, "decision 仅支持 approved / rejected")
    row = await session.scalar(
        select(WritebackApproval)
        .where(WritebackApproval.id == approval_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "审批记录不存在")
    ctx.ensure_tenant(row.tenant_id)
    if row.status != "pending":
        raise HTTPException(409, "审批记录已处理")
    if req.decision == "approved" and row.requested_by == ctx.user_id:
        raise HTTPException(409, "申请人不能审批自己的资金回写")
    row.status = req.decision
    row.approved_by = ctx.user_id if req.decision == "approved" else None
    row.decision_note = req.note
    row.decided_at = datetime.utcnow()
    await session.commit()
    await session.refresh(row)
    return {"approval": approval_to_dict(row)}


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
