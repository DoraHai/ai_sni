"""高风险百度回写的参数绑定审批。"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
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
WRITEBACK_CONFIRMATION = "CONFIRM_BAIDU_WRITEBACK"
IDEMPOTENCY_NOTE_PREFIX = "idempotency-sha256:"
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def shanghai_now_naive() -> datetime:
    """Return a naive Asia/Shanghai value for the project's existing DateTime columns."""
    return datetime.now(_SHANGHAI_TZ).replace(tzinfo=None)


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
        return {
            "baidu_account_id": _positive_id(payload, "baidu_account_id"),
            "new_budget": _positive_money(payload, "new_budget"),
        }
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


def _idempotency_marker(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not 16 <= len(value) <= 128:
        raise WritebackApprovalError("idempotency_key 长度必须为 16~128 字符")
    if any(not (char.isascii() and (char.isalnum() or char in "-_.:")) for char in value):
        raise WritebackApprovalError("idempotency_key 只允许 ASCII 字母、数字和 -_.:")
    return IDEMPOTENCY_NOTE_PREFIX + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _idempotency_lock_id(
    tenant_id: int,
    operator_user_id: int,
    marker: str,
) -> int:
    scope = f"sem-writeback:{tenant_id}:{operator_user_id}:{marker}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(scope).digest()[:8], "big", signed=True)


async def create_self_approved_approval(
    session: AsyncSession,
    *,
    tenant_id: int,
    action_type: str,
    payload: dict[str, Any],
    operator_user_id: int | None,
    confirmation: str | None,
    idempotency_key: str | None = None,
    note: str | None = None,
) -> WritebackApproval:
    """Create the parameter-bound audit row used by one-click live execution."""
    if operator_user_id is None:
        raise WritebackApprovalError("真实资金回写必须使用实名登录账号，不能使用 API Key")
    if confirmation != WRITEBACK_CONFIRMATION:
        raise WritebackApprovalError(
            f"confirmation 必须精确等于 {WRITEBACK_CONFIRMATION}"
        )
    normalized, fingerprint = payload_fingerprint(action_type, payload)
    marker = _idempotency_marker(idempotency_key)
    if marker is not None:
        # Serialize equal client requests without a schema change. The lock is
        # held until the funds intent is committed, so a concurrent replay can
        # only observe and reuse the first approval, never create a second one.
        await session.execute(
            select(func.pg_advisory_xact_lock(
                _idempotency_lock_id(tenant_id, operator_user_id, marker)
            ))
        )
        existing = await session.scalar(
            select(WritebackApproval)
            .where(
                WritebackApproval.tenant_id == tenant_id,
                WritebackApproval.requested_by == operator_user_id,
                WritebackApproval.request_note.like(f"{marker}%"),
            )
            .order_by(WritebackApproval.id.desc())
            .limit(1)
            .with_for_update()
        )
        if existing is not None:
            if (
                existing.action_type != action_type
                or existing.payload_hash != fingerprint
                or existing.payload != normalized
            ):
                raise WritebackApprovalError(
                    "idempotency_key 已用于其他执行参数，请刷新后重试"
                )
            return existing
    now = shanghai_now_naive()
    approval = WritebackApproval(
        tenant_id=tenant_id,
        action_type=action_type,
        payload=normalized,
        payload_hash=fingerprint,
        status="approved",
        request_note=(f"{marker}\n{note}" if marker and note else marker or note),
        requested_by=operator_user_id,
        approved_by=operator_user_id,
        decision_note="本人一次确认",
        created_at=now,
        decided_at=now,
    )
    session.add(approval)
    await session.flush()
    return approval


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
        raise WritebackApprovalError("真实资金回写需要先创建并确认一次性执行记录")
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
    created_at = approval.created_at
    if created_at is None:
        raise WritebackApprovalError("确认记录缺少创建时间，请重新创建确认")
    now = datetime.now(created_at.tzinfo) if created_at.tzinfo else shanghai_now_naive()
    settings = get_settings()
    if settings.baidu_legacy_split_confirmation_enabled:
        raise WritebackApprovalError("旧确认协议兼容期间禁止真实资金回写")
    expires_at = created_at + timedelta(
        minutes=settings.baidu_write_confirmation_ttl_minutes
    )
    if now > expires_at:
        raise WritebackApprovalError("确认记录已过期，请重新创建确认")
    same_operator = (
        approval.approved_by == operator_user_id
        and approval.requested_by == operator_user_id
    )
    if not same_operator:
        raise WritebackApprovalError("确认记录必须由当前实名操作员本人创建并确认")
    approval.status = "consumed"
    approval.consumed_by = operator_user_id
    approval.consumed_at = shanghai_now_naive()
    await session.flush()
    return approval
