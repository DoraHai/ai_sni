"""调价回写台账查询接口（只读）。

回写动作本身在 keywords.py 的 POST /{id}/writeback（归 optimize.keywords edit）；
本模块只查台账，归 verify.adjustments view（与调价台账同组「效果验证」）。
"""
import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.baidu.writeback_approval import (
    ALLOWED_ACTIONS,
    WRITEBACK_CONFIRMATION,
    WritebackApprovalError,
    payload_fingerprint,
    shanghai_now_naive,
)
from app.config import SEM_CUSTOMER_LIVE_WRITE_SCOPES, get_settings
from app.database import get_session
from app.module_scope import ensure_module_access
from app.models import (
    WRITEBACK_ACTION_LABELS,
    WRITEBACK_STATUS_LABELS,
    BaiduAccount,
    BidWriteback,
    WritebackAction,
    WritebackApproval,
)
from app.security.auth import AuthContext, require_scoped_auth
from app.security.sem_identity import ensure_sem_identity_access

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/writeback",
    tags=["调价回写台账"],
    dependencies=[Depends(require_scoped_auth)],
)


def _signed_writeback_change_pct(row: BidWriteback) -> float | None:
    """Normalize historical absolute percentages from the actual bid direction."""
    if row.change_pct is None:
        return None
    value = abs(float(row.change_pct))
    if row.old_bid is None or row.new_bid is None:
        return float(row.change_pct)
    old_bid = float(row.old_bid)
    new_bid = float(row.new_bid)
    if new_bid < old_bid:
        return -value
    if new_bid > old_bid:
        return value
    return 0.0


@router.get("/mode")
async def get_writeback_mode(
    tenant_id: int = Query(...),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """返回当前客户可见的有效回写模式，不暴露其他客户白名单。"""
    ctx.ensure_tenant(tenant_id)
    await ensure_module_access(session, ctx, tenant_id, "sem")
    await ensure_sem_identity_access(session, tenant_id)
    accounts = list(
        (
            await session.scalars(
                select(BaiduAccount)
                .where(
                    BaiduAccount.tenant_id == tenant_id,
                    BaiduAccount.status == "active",
                )
                .order_by(BaiduAccount.id)
            )
        ).all()
    )
    settings = get_settings()
    account_modes = []
    for account in accounts:
        live_scopes = sorted(
            scope
            for scope in SEM_CUSTOMER_LIVE_WRITE_SCOPES
            if not settings.baidu_write_is_dry_run(tenant_id, account.id, scope)
        )
        account_modes.append(
            {
                "baidu_account_id": account.id,
                "account_name": account.baidu_username,
                "external_account_id": str(account.baidu_ucid),
                "live_scopes": live_scopes,
                "mode": "limited_live" if live_scopes else "dry_run",
            }
        )
    live_scopes = sorted(
        {
            scope
            for account in account_modes
            for scope in account["live_scopes"]
        }
    )
    return {
        "tenant_id": tenant_id,
        "mode": "limited_live" if live_scopes else "dry_run",
        "writeback_enabled": bool(live_scopes),
        "live_scopes": live_scopes,
        "accounts": account_modes,
    }


class ApprovalRequest(BaseModel):
    tenant_id: int
    action_type: str
    payload: dict
    note: str | None = Field(None, max_length=1000)
    confirmation: str | None = None


class ApprovalDecision(BaseModel):
    decision: str
    note: str | None = Field(None, max_length=1000)


class ReconciliationDecision(BaseModel):
    tenant_id: int
    decision: Literal["confirmed_executed", "confirmed_not_executed"]
    note: str = Field(..., min_length=4, max_length=1000)


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
    """创建本人高风险资金回写确认；参数会被规范化并绑定指纹。"""
    ctx.ensure_tenant(req.tenant_id)
    if ctx.user_id is None:
        raise HTTPException(403, "资金回写确认必须使用实名登录账号")
    settings = get_settings()
    if req.confirmation not in (None, WRITEBACK_CONFIRMATION):
        raise HTTPException(400, f"confirmation 必须精确等于 {WRITEBACK_CONFIRMATION}")
    legacy_pending = req.confirmation is None
    if legacy_pending and not settings.baidu_legacy_split_confirmation_enabled:
        raise HTTPException(400, f"confirmation 必须精确等于 {WRITEBACK_CONFIRMATION}")
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
        status="pending" if legacy_pending else "approved",
        request_note=req.note,
        requested_by=ctx.user_id,
        approved_by=None if legacy_pending else ctx.user_id,
        decision_note=None if legacy_pending else "本人二次确认",
        decided_at=None if legacy_pending else shanghai_now_naive(),
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
    """处理历史待确认记录；只能由原实名操作员本人确认或取消。"""
    if ctx.user_id is None:
        raise HTTPException(403, "确认操作必须使用实名登录账号")
    if req.decision not in {"approved", "rejected"}:
        raise HTTPException(400, "decision 仅支持 approved / rejected")
    row = await session.scalar(
        select(WritebackApproval)
        .where(WritebackApproval.id == approval_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "审批记录不存在")
    await ensure_module_access(session, ctx, row.tenant_id, "sem")
    await ensure_sem_identity_access(session, row.tenant_id)
    if row.status != "pending":
        raise HTTPException(409, "审批记录已处理")
    if (
        row.requested_by != ctx.user_id
        and not get_settings().baidu_legacy_split_confirmation_enabled
    ):
        raise HTTPException(409, "资金回写只能由创建确认的实名操作员本人处理")
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
        "approval_id": r.approval_id,
        "suggestion_id": r.suggestion_id,
        "keyword_id": r.keyword_id,
        "keyword": r.keyword,
        "campaign_id": r.campaign_id,
        "campaign_name": r.campaign_name,
        "adgroup_id": r.adgroup_id,
        "old_bid": float(r.old_bid) if r.old_bid is not None else None,
        "new_bid": float(r.new_bid),
        "change_pct": _signed_writeback_change_pct(r),
        "dry_run": r.dry_run,
        "status": r.status,
        "status_label": WRITEBACK_STATUS_LABELS.get(r.status, r.status),
        "error_msg": r.error_msg,
        "operator_name": r.operator_name,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "executed_at": r.executed_at.isoformat() if r.executed_at else None,
        "reconciliation_result": r.reconciliation_result,
        "reconciliation_note": r.reconciliation_note,
        "reconciled_by": r.reconciled_by,
        "reconciled_at": r.reconciled_at.isoformat() if r.reconciled_at else None,
    }


@router.get("")
async def list_writebacks(
    tenant_id: int = Query(..., description="本地租户 ID"),
    status: str | None = Query(
        None, description="success/failed/dry_run/pending/reconcile，传 all 或空看全部"
    ),
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


def _queue_stage(status: str, dry_run: bool) -> str:
    if status == "failed":
        return "failed"
    if not dry_run and status in {"pending", "reconcile"}:
        return "reconciliation_required"
    if dry_run or status == "dry_run":
        return "pending_writeback"
    if status == "success":
        return "executed"
    return "reconciliation_required"


@router.post("/queue/{record_type}/{record_id}/reconcile")
async def reconcile_writeback(
    record_type: Literal["bid", "action"],
    record_id: int,
    req: ReconciliationDecision,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """异人确认真实写回结果；保留原异常与对账说明，解除同对象安全锁。"""
    if ctx.user_id is None:
        raise HTTPException(403, "人工对账必须使用实名登录账号")
    note = req.note.strip()
    if len(note) < 4:
        raise HTTPException(400, "请填写至少 4 个字的对账依据")
    ctx.ensure_tenant(req.tenant_id)
    model = BidWriteback if record_type == "bid" else WritebackAction
    row = await session.scalar(
        select(model)
        .where(model.id == record_id, model.tenant_id == req.tenant_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "待对账记录不存在")
    if row.dry_run or row.status not in {"pending", "reconcile"}:
        raise HTTPException(409, "该记录不是待人工对账的真实写回")
    if row.operator_user_id is not None and row.operator_user_id == ctx.user_id:
        raise HTTPException(409, "真实写回执行人不能确认自己的对账结论")

    original_error = row.error_msg
    row.reconciliation_result = req.decision
    row.reconciliation_note = (
        f"{note}\n原异常：{original_error}" if original_error else note
    )
    row.reconciled_by = ctx.user_id
    row.reconciled_at = datetime.utcnow()
    if req.decision == "confirmed_executed":
        row.status = "success"
        row.error_msg = None
    else:
        row.status = "failed"
        row.error_msg = f"人工对账确认未执行：{note}"[:2000]
    await session.commit()
    await session.refresh(row)
    return {
        "status": row.status,
        "record_type": record_type,
        "record_id": row.id,
        "reconciliation_result": row.reconciliation_result,
        "reconciliation_note": row.reconciliation_note,
        "reconciled_by": row.reconciled_by,
        "reconciled_at": row.reconciled_at.isoformat() if row.reconciled_at else None,
    }


@router.get("/queue")
async def list_writeback_queue(
    tenant_id: int = Query(...),
    limit: int = Query(200, ge=1, le=500),
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """统一审计视图：演练记录是待回写，不冒充百度已执行。"""
    ctx.ensure_tenant(tenant_id)
    mode = await get_writeback_mode(tenant_id, ctx, session)
    bids = list((await session.scalars(
        select(BidWriteback).where(BidWriteback.tenant_id == tenant_id)
        .order_by(BidWriteback.id.desc()).limit(limit)
    )).all())
    actions = list((await session.scalars(
        select(WritebackAction).where(WritebackAction.tenant_id == tenant_id)
        .order_by(WritebackAction.id.desc()).limit(limit)
    )).all())
    items = [
        {
            "key": f"bid:{row.id}", "kind": "关键词调价", "target": row.keyword,
            "approval_id": row.approval_id,
            "before": float(row.old_bid) if row.old_bid is not None else None,
            "after": float(row.new_bid), "stage": _queue_stage(row.status, row.dry_run),
            "operator": row.operator_name, "created_at": row.created_at.isoformat() if row.created_at else None,
            "error": row.error_msg, "reconciliation_result": row.reconciliation_result,
            "reconciliation_note": row.reconciliation_note,
        }
        for row in bids
    ] + [
        {
            "key": f"action:{row.id}", "kind": WRITEBACK_ACTION_LABELS.get(row.action_type, row.action_type),
            "approval_id": row.approval_id,
            "target": row.word, "before": float(row.old_value) if row.old_value is not None else None,
            "after": float(row.new_value) if row.new_value is not None else None,
            "stage": _queue_stage(row.status, row.dry_run), "operator": row.operator_name,
            "created_at": row.created_at.isoformat() if row.created_at else None, "error": row.error_msg,
            "reconciliation_result": row.reconciliation_result,
            "reconciliation_note": row.reconciliation_note,
        }
        for row in actions
    ]
    items.sort(key=lambda item: item["created_at"] or "", reverse=True)
    items = items[:limit]
    counts = {
        "pending_writeback": 0,
        "reconciliation_required": 0,
        "executed": 0,
        "failed": 0,
    }
    for item in items:
        counts[item["stage"]] += 1
    return {
        "writeback_enabled": mode["writeback_enabled"],
        "mode": mode["mode"],
        "live_scopes": mode["live_scopes"],
        "counts": counts,
        "items": items,
    }
