"""高风险百度回写的参数绑定审批。"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.writeback_approval import WritebackApproval


ACTION_KEYWORD_BID = "keyword_bid"
ACTION_ADGROUP_BID = "adgroup_bid"
ACTION_CAMPAIGN_BUDGET = "campaign_budget"
ACTION_ACCOUNT_BUDGET = "account_budget"
ALLOWED_ACTIONS = frozenset(
    {
        ACTION_KEYWORD_BID,
        ACTION_ADGROUP_BID,
        ACTION_CAMPAIGN_BUDGET,
        ACTION_ACCOUNT_BUDGET,
    }
)


class WritebackApprovalError(ValueError):
    pass


def _positive_id(payload: dict[str, Any], key: str) -> int:
    try:
        raw = payload[key]
        if isinstance(raw, bool):
            raise ValueError
        numeric = float(raw)
        if not math.isfinite(numeric) or not numeric.is_integer():
            raise ValueError
        value = int(numeric)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise WritebackApprovalError(f"{key} 必须是正整数") from exc
    if value <= 0 or value > 9_223_372_036_854_775_807:
        raise WritebackApprovalError(f"{key} 必须是正整数")
    return value


def _positive_money(payload: dict[str, Any], key: str) -> float:
    try:
        raw = payload[key]
        if isinstance(raw, bool):
            raise ValueError
        value = float(raw)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise WritebackApprovalError(f"{key} 必须是有限正数") from exc
    if not math.isfinite(value) or value <= 0:
        raise WritebackApprovalError(f"{key} 必须是有限正数")
    value = round(value, 2)
    if value < 0.01:
        raise WritebackApprovalError(f"{key} 最小精度为 0.01")
    return value


def normalize_payload(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """只保留审批所需字段，并统一数值精度。"""
    if not isinstance(payload, dict):
        raise WritebackApprovalError("payload 必须是对象")
    if action_type == ACTION_KEYWORD_BID:
        return {
            "keyword_id": _positive_id(payload, "keyword_id"),
            "new_bid": _positive_money(payload, "new_bid"),
        }
    if action_type == ACTION_ADGROUP_BID:
        return {
            "adgroup_id": _positive_id(payload, "adgroup_id"),
            "new_price": _positive_money(payload, "new_price"),
        }
    if action_type == ACTION_CAMPAIGN_BUDGET:
        return {
            "campaign_id": _positive_id(payload, "campaign_id"),
            "new_budget": _positive_money(payload, "new_budget"),
        }
    if action_type == ACTION_ACCOUNT_BUDGET:
        return {"new_budget": _positive_money(payload, "new_budget")}
    raise WritebackApprovalError(f"不支持审批的回写类型：{action_type}")


def payload_fingerprint(action_type: str, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    normalized = normalize_payload(action_type, payload)
    raw = json.dumps(
        {"action_type": action_type, "payload": normalized},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return normalized, hashlib.sha256(raw).hexdigest()


async def claim_approval(
    session: AsyncSession,
    *,
    approval_id: int | None,
    tenant_id: int,
    action_type: str,
    payload: dict[str, Any],
    operator_user_id: int | None,
) -> WritebackApproval:
    if operator_user_id is None:
        raise WritebackApprovalError("真实资金回写必须使用实名登录账号，不能使用 API Key")
    if approval_id is None:
        raise WritebackApprovalError("真实资金回写需要先提交并通过异人审批")
    normalized, fingerprint = payload_fingerprint(action_type, payload)
    approval = await session.scalar(
        select(WritebackApproval)
        .where(WritebackApproval.id == approval_id)
        .with_for_update()
    )
    if approval is None or approval.tenant_id != tenant_id:
        raise WritebackApprovalError("审批记录不存在或不属于当前客户")
    if approval.status != "approved":
        raise WritebackApprovalError("审批记录未通过或已经使用")
    if approval.action_type != action_type or approval.payload_hash != fingerprint:
        raise WritebackApprovalError("执行参数与审批参数不一致，请重新申请审批")
    if approval.payload != normalized:
        raise WritebackApprovalError("审批参数校验失败，请重新申请审批")
    if approval.approved_by is None or approval.approved_by == operator_user_id:
        raise WritebackApprovalError("审批人与执行人必须是不同用户")
    approval.status = "consumed"
    approval.consumed_by = operator_user_id
    approval.consumed_at = datetime.utcnow()
    await session.flush()
    return approval
