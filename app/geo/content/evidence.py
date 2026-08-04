"""Rules that decide whether a fact can support publishable content."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


def _coerce_expiry(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    # Accept ISO date or datetime prefixes.
    return date.fromisoformat(text[:10])


def evidence_issues(facts: list[dict[str, Any]], *, today: date | None = None) -> dict[int, list[str]]:
    """Return per-fact blockers for publishable evidence.

    Missing ``status`` is treated as active (legacy rows). ``trust_level`` must be
    ``verified`` for publishable use; drafts / needs_review are blocked.
    """
    reference_date = today or date.today()
    result: dict[int, list[str]] = {}
    for fact in facts:
        fact_id = fact.get("id")
        if fact_id is None:
            continue
        issues: list[str] = []
        status = fact.get("status") or "active"
        if status != "active":
            issues.append("not_active")
        if fact.get("trust_level") != "verified":
            issues.append("not_verified")
        if not str(fact.get("source_name") or "").strip():
            issues.append("missing_source")
        expires_at = _coerce_expiry(fact.get("expires_at"))
        if expires_at is not None and expires_at <= reference_date:
            issues.append("expired")
        if issues:
            result[int(fact_id)] = issues
    return result


def eligible_facts(facts: list[dict[str, Any]], *, today: date | None = None) -> list[dict[str, Any]]:
    blocked = evidence_issues(facts, today=today)
    return [fact for fact in facts if fact.get("id") not in blocked]


def summarize_evidence_blockers(
    facts: list[dict[str, Any]], *, today: date | None = None, min_eligible: int = 3
) -> tuple[bool, str, str]:
    """Return (ok, message, action) for rule / gate surfaces."""
    issues = evidence_issues(facts, today=today)
    eligible = eligible_facts(facts, today=today)
    if len(eligible) >= min_eligible:
        return True, f"可发布证据 {len(eligible)}/{min_eligible}", ""
    reasons: list[str] = []
    if any("expired" in v for v in issues.values()):
        reasons.append("过期")
    if any("not_verified" in v for v in issues.values()):
        reasons.append("未核验")
    if any("missing_source" in v for v in issues.values()):
        reasons.append("缺来源")
    if any("not_active" in v for v in issues.values()):
        reasons.append("已归档")
    reason_text = "、".join(reasons) if reasons else "不足"
    return (
        False,
        f"可发布证据 {len(eligible)}/{min_eligible}（{reason_text}）",
        "请核验事实、补来源，并移除或更新已过期事实后再发布",
    )
