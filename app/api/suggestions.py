"""AI 调价建议接口。

建议引擎产出见 app/suggestions/，本模块做查询 + 状态流转（采纳/忽略）+ 手动触发。
回写出价（最终执行价 → 百度 updateWord）见 app/api/keywords.py 的 /writeback 端点。
「采纳」状态：回写成功后自动置 adopted；也可人工手动标记。
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import (
    CONFIDENCE_LABELS,
    SUGGESTION_TYPE_LABELS,
    Suggestion,
    Tenant,
    User,
)
from app.security.auth import AuthContext, require_scoped_auth
from app.suggestions import run_suggestions_for_tenant

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/suggestions",
    tags=["AI 调价建议"],
    dependencies=[Depends(require_scoped_auth)],
)

VALID_STATUS = {"pending", "adopted", "ignored"}
VALID_HANDLING_STATUS = {"todo", "in_progress", "waiting_writeback", "completed", "rejected"}
HANDLING_STATUS_LABELS = {
    "todo": "待处理",
    "in_progress": "处理中",
    "waiting_writeback": "待回写",
    "completed": "已完成",
    "rejected": "已驳回",
}
# min_confidence 过滤：传 mid 看 high+mid，传 low 看全部
CONFIDENCE_TIERS = {"high": ["high"], "mid": ["high", "mid"], "low": ["high", "mid", "low"]}


def _effective_handling_status(s: Suggestion) -> str:
    if s.status == "adopted":
        return "completed"
    if s.status == "ignored":
        return "rejected"
    return s.handling_status or "todo"


def _to_dict(s: Suggestion, assignee_names: dict[int, str] | None = None) -> dict:
    assignee_names = assignee_names or {}
    handling_status = _effective_handling_status(s)
    return {
        "id": s.id,
        "rule_code": s.rule_code,
        "suggestion_type": s.suggestion_type,
        "type_label": SUGGESTION_TYPE_LABELS.get(s.suggestion_type, s.suggestion_type),
        "priority": s.priority,
        "confidence": s.confidence,
        "confidence_label": CONFIDENCE_LABELS.get(s.confidence, s.confidence),
        "current_bid": float(s.current_bid) if s.current_bid is not None else None,
        "suggested_bid": float(s.suggested_bid) if s.suggested_bid is not None else None,
        "change_pct": float(s.change_pct) if s.change_pct is not None else None,
        "reason": s.reason,
        "signals": s.signals or {},
        "report_date": s.report_date.isoformat(),
        "keyword_id": s.keyword_id,
        "keyword": s.keyword,
        "campaign_id": s.campaign_id,
        "campaign_name": s.campaign_name,
        "adgroup_id": s.adgroup_id,
        "status": s.status,
        "handling_status": handling_status,
        "handling_status_label": HANDLING_STATUS_LABELS.get(handling_status, handling_status),
        "assignee_id": s.assignee_id,
        "assignee_name": assignee_names.get(s.assignee_id) if s.assignee_id else None,
        "due_at": s.due_at.isoformat() if s.due_at else None,
        "workflow_updated_at": s.workflow_updated_at.isoformat() if s.workflow_updated_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "adopted_at": s.adopted_at.isoformat() if s.adopted_at else None,
    }


@router.get("")
async def list_suggestions(
    tenant_id: int = Query(..., description="本地租户 ID"),
    status: str | None = Query(
        "pending", description="pending/adopted/ignored，传 all 看全部"
    ),
    suggestion_type: str | None = Query(
        None, description="raise/lower/optimize/pause_warn"
    ),
    priority: str | None = Query(None, description="P0~P5"),
    min_confidence: str | None = Query(None, description="high/mid/low，按及以上过滤"),
    limit: int = Query(200, le=500),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """建议列表 + 按类型计数。默认只看待处理（pending）。按优先级、数据日期降序。"""
    cond = [Suggestion.tenant_id == tenant_id]
    if status and status != "all":
        cond.append(Suggestion.status == status)
    if suggestion_type:
        cond.append(Suggestion.suggestion_type == suggestion_type)
    if priority:
        cond.append(Suggestion.priority == priority)
    if min_confidence and min_confidence in CONFIDENCE_TIERS:
        cond.append(Suggestion.confidence.in_(CONFIDENCE_TIERS[min_confidence]))

    rows = (
        await session.scalars(
            select(Suggestion)
            .where(*cond)
            .order_by(
                Suggestion.priority,
                Suggestion.report_date.desc(),
                Suggestion.id.desc(),
            )
            .limit(limit)
        )
    ).all()
    assignee_ids = {row.assignee_id for row in rows if row.assignee_id}
    assignee_names = {}
    if assignee_ids:
        users = (await session.scalars(select(User).where(User.id.in_(assignee_ids)))).all()
        assignee_names = {user.id: user.display_name or user.username for user in users}

    # 待处理按类型计数（不受筛选影响，给侧边栏角标/tab 用）
    count_rows = (
        await session.execute(
            select(Suggestion.suggestion_type, func.count())
            .where(Suggestion.tenant_id == tenant_id, Suggestion.status == "pending")
            .group_by(Suggestion.suggestion_type)
        )
    ).all()
    type_counts = {t: int(n) for t, n in count_rows}

    return {
        "total_pending": sum(type_counts.values()),
        "type_counts": type_counts,
        "suggestions": [_to_dict(s, assignee_names) for s in rows],
    }


@router.get("/assignees")
async def list_assignees(
    tenant_id: int = Query(..., description="本地租户 ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """返回当前客户可分配的内部成员；不暴露账号权限或认证信息。"""
    users = (await session.scalars(
        select(User).where(
            User.is_active.is_(True),
            or_(User.tenant_id.is_(None), User.tenant_id == tenant_id),
        ).order_by(User.display_name, User.username)
    )).all()
    return {"assignees": [
        {"id": user.id, "name": user.display_name or user.username}
        for user in users
    ]}


class SuggestionWorkflowRequest(BaseModel):
    assignee_id: int | None = None
    clear_assignee: bool = False
    handling_status: str | None = None
    due_at: datetime | None = None
    clear_due_at: bool = False


@router.patch("/{suggestion_id}/workflow")
async def update_workflow(
    suggestion_id: int,
    req: SuggestionWorkflowRequest,
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_scoped_auth),
) -> dict:
    """更新内部负责人、处理状态和截止时间；不触发任何百度回写。"""
    suggestion = await session.get(Suggestion, suggestion_id)
    if suggestion is None:
        raise HTTPException(404, "建议不存在，可能已被刷新")
    ctx.ensure_tenant(suggestion.tenant_id)
    if req.handling_status is not None:
        if req.handling_status not in VALID_HANDLING_STATUS:
            raise HTTPException(400, f"无效处理状态，应为 {sorted(VALID_HANDLING_STATUS)}")
        suggestion.handling_status = req.handling_status
        if req.handling_status == "completed":
            suggestion.status = "adopted"
            suggestion.adopted_at = datetime.utcnow()
        elif req.handling_status == "rejected":
            suggestion.status = "ignored"
            suggestion.adopted_at = None
        elif suggestion.status in {"adopted", "ignored"}:
            suggestion.status = "pending"
            suggestion.adopted_at = None
    if req.clear_assignee:
        suggestion.assignee_id = None
    elif req.assignee_id is not None:
        user = await session.get(User, req.assignee_id)
        if user is None or not user.is_active:
            raise HTTPException(400, "负责人不存在或已停用")
        if user.tenant_id is not None and user.tenant_id != suggestion.tenant_id:
            raise HTTPException(400, "负责人不属于当前客户")
        suggestion.assignee_id = user.id
    if req.clear_due_at:
        suggestion.due_at = None
    elif req.due_at is not None:
        suggestion.due_at = req.due_at.replace(tzinfo=None)
    suggestion.workflow_updated_by = ctx.user_id
    suggestion.workflow_updated_at = datetime.utcnow()
    await session.commit()
    assignee_names = {}
    if suggestion.assignee_id:
        user = await session.get(User, suggestion.assignee_id)
        if user:
            assignee_names[user.id] = user.display_name or user.username
    return {"status": "ok", "suggestion": _to_dict(suggestion, assignee_names)}


@router.patch("/{suggestion_id}/status")
async def update_status(
    suggestion_id: int,
    status: str = Query(..., description="adopted（已采纳）/ ignored（已忽略）/ pending（恢复）"),
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_scoped_auth),
) -> dict:
    """更新建议状态。adopted = 已采纳（回写成功会自动置，也可人工标记）。"""
    if status not in VALID_STATUS:
        raise HTTPException(400, f"无效状态，应为 {sorted(VALID_STATUS)}")
    s = await session.get(Suggestion, suggestion_id)
    if s is None:
        raise HTTPException(404, "建议不存在，可能已被刷新")
    ctx.ensure_tenant(s.tenant_id)
    s.status = status
    s.adopted_at = datetime.utcnow() if status == "adopted" else None
    if status == "adopted":
        s.handling_status = "completed"
    elif status == "ignored":
        s.handling_status = "rejected"
    elif s.handling_status in {"completed", "rejected"}:
        s.handling_status = "todo"
    s.workflow_updated_by = ctx.user_id
    s.workflow_updated_at = datetime.utcnow()
    await session.commit()
    return {"status": "ok", "suggestion": _to_dict(s)}


@router.post("/run")
async def run_suggestions(
    tenant_id: int = Query(..., description="本地租户 ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """手动触发建议引擎（正常由每日定时任务跑）。窗口锚定最近有数据日。"""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在，请确认 tenant_id")
    n = await run_suggestions_for_tenant(session, tenant)
    return {"status": "ok", "tenant_id": tenant_id, "suggestions_written": n}
