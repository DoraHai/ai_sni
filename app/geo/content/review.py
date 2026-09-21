"""GEO D4 后阶段：内容审校状态机。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.permissions import CUSTOMER_ROLE

REVIEW_NONE = "none"
REVIEW_PENDING = "pending"
REVIEW_APPROVED = "approved"
REVIEW_REJECTED = "rejected"

REVIEW_STATUSES = (REVIEW_NONE, REVIEW_PENDING, REVIEW_APPROVED, REVIEW_REJECTED)
REVIEW_AUDIT_SCHEMA = "geo.review.audit.v1"


def is_tenant_customer_reviewer(ctx: Any) -> bool:
    """Return whether a signed-in, tenant-bound view account may decide reviews."""
    return (
        getattr(ctx, "user_id", None) is not None
        and getattr(ctx, "tenant_id", None) is not None
        and getattr(ctx, "role_name", None) == CUSTOMER_ROLE
        and getattr(ctx, "permissions", {}).get("geo.content") == "view"
    )


def can_decide_customer_review(ctx: Any) -> bool:
    """Keep existing editors while granting one narrow action to customer reviewers."""
    can_edit = getattr(ctx, "can_edit", None)
    return bool(
        getattr(ctx, "is_superadmin", False)
        or (callable(can_edit) and can_edit("geo.content"))
        or is_tenant_customer_reviewer(ctx)
    )


def normalize_review_status(value: str | None) -> str:
    text = str(value or REVIEW_NONE).strip().lower()
    return text if text in REVIEW_STATUSES else REVIEW_NONE


def can_submit_review(*, has_article: bool, review_status: str) -> tuple[bool, str]:
    if not has_article:
        return False, "请先生成母稿后再提交审校"
    status = normalize_review_status(review_status)
    if status == REVIEW_PENDING:
        return False, "已在审校中"
    if status == REVIEW_APPROVED:
        return False, "已通过审校；如需重审请先退回"
    return True, ""


def _audit_events(task: Any) -> list[dict[str, Any]]:
    audit = getattr(task, "review_audit", None)
    if not isinstance(audit, dict) or audit.get("schema_version") != REVIEW_AUDIT_SCHEMA:
        return []
    events = audit.get("events")
    return [dict(item) for item in events if isinstance(item, dict)] if isinstance(events, list) else []


def _write_event(task: Any, event: dict[str, Any]) -> None:
    task.review_audit = {
        "schema_version": REVIEW_AUDIT_SCHEMA,
        "events": [*_audit_events(task), event],
    }


def _actor_event(
    event_type: str,
    *,
    actor_user_id: int | None,
    actor_role: str | None,
    tenant_id: int | None,
    article_id: int | None,
    occurred_at: datetime,
) -> dict[str, Any]:
    role = str(actor_role or "").strip()
    if (
        not isinstance(actor_user_id, int)
        or isinstance(actor_user_id, bool)
        or actor_user_id <= 0
        or not role
    ):
        raise ValueError("审核流程需要已登录且角色明确的操作人员")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0
        for value in (tenant_id, article_id)
    ):
        raise ValueError("审核流程缺少当前客户或母稿版本")
    event_time = occurred_at
    if event_time.tzinfo is not None:
        event_time = event_time.astimezone(timezone.utc).replace(tzinfo=None)
    return {
        "event": event_type,
        "actor_user_id": int(actor_user_id),
        "actor_role": role,
        "tenant_id": int(tenant_id),
        "article_id": int(article_id),
        "occurred_at": event_time.isoformat() + "Z",
    }


def _event_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _valid_actor_event(
    event: dict[str, Any], *, event_type: str, tenant_id: int, article_id: int
) -> bool:
    actor_user_id = event.get("actor_user_id")
    return bool(
        event.get("event") == event_type
        and event.get("tenant_id") == tenant_id
        and event.get("article_id") == article_id
        and isinstance(actor_user_id, int)
        and not isinstance(actor_user_id, bool)
        and actor_user_id > 0
        and str(event.get("actor_role") or "").strip()
        and _event_time(event.get("occurred_at")) is not None
    )


def current_review_receipt(task: Any, *, article_id: int | None = None) -> dict[str, Any] | None:
    """Return a complete submitted -> approved receipt for the current tenant/version."""
    events = _audit_events(task)
    if len(events) < 2:
        return None
    decision = events[-1]
    submission = events[-2]
    tenant_id = getattr(task, "tenant_id", None)
    expected_article_id = article_id if article_id is not None else submission.get("article_id")
    if (
        not isinstance(tenant_id, int)
        or isinstance(tenant_id, bool)
        or not isinstance(expected_article_id, int)
        or isinstance(expected_article_id, bool)
        or not _valid_actor_event(
            submission, event_type="submitted", tenant_id=tenant_id, article_id=expected_article_id
        )
        or not _valid_actor_event(
            decision, event_type="approved", tenant_id=tenant_id, article_id=expected_article_id
        )
    ):
        return None
    submission_time = _event_time(submission["occurred_at"])
    decision_time = _event_time(decision["occurred_at"])
    if submission_time is None or decision_time is None or decision_time < submission_time:
        return None
    return {"submission": submission, "decision": decision}


def current_review_submission(task: Any, *, article_id: int | None = None) -> dict[str, Any] | None:
    events = _audit_events(task)
    if not events:
        return None
    candidate = None
    if events[-1].get("event") == "submitted":
        candidate = events[-1]
    elif len(events) >= 2 and events[-2].get("event") == "submitted":
        candidate = events[-2]
    tenant_id = getattr(task, "tenant_id", None)
    expected_article_id = article_id if article_id is not None else (
        candidate.get("article_id") if candidate else None
    )
    if (
        candidate is None
        or not isinstance(tenant_id, int)
        or isinstance(tenant_id, bool)
        or not isinstance(expected_article_id, int)
        or isinstance(expected_article_id, bool)
        or not _valid_actor_event(
            candidate,
            event_type="submitted",
            tenant_id=tenant_id,
            article_id=expected_article_id,
        )
    ):
        return None
    return candidate


def apply_submit(
    task: Any,
    *,
    note: str | None = None,
    submitter_id: int | None = None,
    submitter_role: str | None = None,
    tenant_id: int | None = None,
    article_id: int | None = None,
    occurred_at: datetime | None = None,
) -> None:
    if getattr(task, "tenant_id", tenant_id) != tenant_id:
        raise ValueError("审核提交客户与任务客户不一致")
    ok, message = can_submit_review(
        has_article=True,
        review_status=getattr(task, "review_status", None),
    )
    if not ok:
        raise ValueError(message)
    event = _actor_event(
        "submitted",
        actor_user_id=submitter_id,
        actor_role=submitter_role,
        tenant_id=tenant_id,
        article_id=article_id,
        occurred_at=occurred_at or datetime.utcnow(),
    )
    task.review_status = REVIEW_PENDING
    task.reviewed_at = None
    task.reviewed_by = None
    if submitter_id is not None:
        task.review_submitted_by = submitter_id
    _write_event(task, event)
    if note is not None:
        text = str(note).strip()
        task.review_note = text or None


def apply_decision(
    task: Any,
    *,
    decision: str,
    note: str | None,
    reviewer_id: int | None,
    reviewer_role: str | None = None,
    tenant_id: int | None = None,
    article_id: int | None = None,
    occurred_at: datetime | None = None,
) -> None:
    if getattr(task, "tenant_id", tenant_id) != tenant_id:
        raise ValueError("审核决定客户与任务客户不一致")
    decision_norm = str(decision or "").strip().lower()
    if decision_norm not in {REVIEW_APPROVED, REVIEW_REJECTED}:
        raise ValueError("decision 仅支持 approved / rejected")
    if normalize_review_status(task.review_status) != REVIEW_PENDING:
        raise ValueError("仅「待审」任务可审批")
    now = occurred_at or datetime.utcnow()
    event = _actor_event(
        decision_norm,
        actor_user_id=reviewer_id,
        actor_role=reviewer_role,
        tenant_id=tenant_id,
        article_id=article_id,
        occurred_at=now,
    )
    events = _audit_events(task)
    submission = events[-1] if events else None
    if not submission or not _valid_actor_event(
        submission,
        event_type="submitted",
        tenant_id=tenant_id,
        article_id=article_id,
    ):
        raise ValueError("缺少当前客户和母稿版本的独立提交审核事件，请重新提交审核")
    submission_time = _event_time(submission["occurred_at"])
    if submission_time is None or submission_time > now:
        raise ValueError("提交审核事件时间无效，请重新提交审核")
    # One customer review is sufficient; author and reviewer may be the same account.
    task.review_status = decision_norm
    task.review_note = (note or "").strip() or None
    task.reviewed_by = reviewer_id
    task.reviewed_at = now
    _write_event(task, event)


def invalidate_review(task: Any) -> None:
    """母稿变更后作废已有审校结果。"""
    task.review_status = REVIEW_NONE
    task.review_note = None
    task.review_submitted_by = None
    task.reviewed_by = None
    task.reviewed_at = None


def assert_review_approved(task: Any, *, article_id: int | None = None) -> None:
    status = normalize_review_status(getattr(task, "review_status", None))
    if status != REVIEW_APPROVED:
        raise ValueError(
            f"未通过审校（当前：{status}），请提交审校并审批通过后再发布回填"
        )
    if current_review_receipt(task, article_id=article_id) is None:
        raise ValueError("审核记录缺少当前客户、角色或版本依据，请重新提交并审核")


def review_payload(task: Any, *, article_id: int | None = None) -> dict[str, Any]:
    status = normalize_review_status(getattr(task, "review_status", None))
    receipt = current_review_receipt(task, article_id=article_id)
    submission = current_review_submission(task, article_id=article_id)
    return {
        "review_status": status,
        "review_note": getattr(task, "review_note", None),
        "reviewed_by": getattr(task, "reviewed_by", None),
        "reviewed_at": (
            task.reviewed_at.isoformat()
            if getattr(task, "reviewed_at", None) is not None
            else None
        ),
        "review_approved": status == REVIEW_APPROVED and receipt is not None,
        "review_audit_verified": receipt is not None,
        "review_submission_event": submission,
        "review_decision_event": receipt.get("decision") if receipt else None,
        "can_submit_review": status in {REVIEW_NONE, REVIEW_REJECTED},
        "can_decide_review": status == REVIEW_PENDING,
    }
