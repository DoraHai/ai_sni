"""GEO D4 后阶段：内容审校状态机。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

REVIEW_NONE = "none"
REVIEW_PENDING = "pending"
REVIEW_APPROVED = "approved"
REVIEW_REJECTED = "rejected"

REVIEW_STATUSES = (REVIEW_NONE, REVIEW_PENDING, REVIEW_APPROVED, REVIEW_REJECTED)


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


def apply_submit(
    task: Any, *, note: str | None = None, submitter_id: int | None = None
) -> None:
    ok, message = can_submit_review(
        has_article=True,
        review_status=getattr(task, "review_status", None),
    )
    if not ok:
        raise ValueError(message)
    task.review_status = REVIEW_PENDING
    task.reviewed_at = None
    task.reviewed_by = None
    if submitter_id is not None:
        task.review_submitted_by = submitter_id
    if note is not None:
        text = str(note).strip()
        task.review_note = text or None


def apply_decision(
    task: Any,
    *,
    decision: str,
    note: str | None,
    reviewer_id: int | None,
    allow_self_approve: bool | None = None,
) -> None:
    decision_norm = str(decision or "").strip().lower()
    if decision_norm not in {REVIEW_APPROVED, REVIEW_REJECTED}:
        raise ValueError("decision 仅支持 approved / rejected")
    if normalize_review_status(task.review_status) != REVIEW_PENDING:
        raise ValueError("仅「待审」任务可审批")
    if decision_norm == REVIEW_APPROVED and reviewer_id is None:
        raise ValueError("审批通过需要已登录的审核人员账号，API Key 不能代替审核身份")
    if allow_self_approve is None:
        try:
            from app.config import get_settings

            allow_self_approve = bool(
                getattr(get_settings(), "geo_allow_self_review", False)
            )
        except Exception:  # noqa: BLE001
            allow_self_approve = False
    if (
        not allow_self_approve
        and decision_norm == REVIEW_APPROVED
        and reviewer_id is not None
    ):
        submitter = getattr(task, "review_submitted_by", None)
        if submitter is None:
            submitter = getattr(task, "owner_user_id", None)
        if submitter is not None and int(submitter) == int(reviewer_id):
            raise ValueError("禁止自审自批：请由其他账号审批通过后再发布")
    task.review_status = decision_norm
    task.review_note = (note or "").strip() or None
    task.reviewed_by = reviewer_id
    task.reviewed_at = datetime.utcnow()


def invalidate_review(task: Any) -> None:
    """母稿变更后作废已有审校结果。"""
    task.review_status = REVIEW_NONE
    task.review_note = None
    task.review_submitted_by = None
    task.reviewed_by = None
    task.reviewed_at = None


def assert_review_approved(task: Any) -> None:
    status = normalize_review_status(getattr(task, "review_status", None))
    if status != REVIEW_APPROVED:
        raise ValueError(
            f"未通过审校（当前：{status}），请提交审校并审批通过后再发布回填"
        )


def review_payload(task: Any) -> dict[str, Any]:
    status = normalize_review_status(getattr(task, "review_status", None))
    return {
        "review_status": status,
        "review_note": getattr(task, "review_note", None),
        "reviewed_by": getattr(task, "reviewed_by", None),
        "reviewed_at": (
            task.reviewed_at.isoformat()
            if getattr(task, "reviewed_at", None) is not None
            else None
        ),
        "review_approved": status == REVIEW_APPROVED,
        "can_submit_review": status in {REVIEW_NONE, REVIEW_REJECTED},
        "can_decide_review": status == REVIEW_PENDING,
    }
