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
        "请核验事实、补来源，并移除或更新已过期事实后再生成/发布",
    )


ISSUE_LABELS = {
    "not_active": "已归档",
    "not_verified": "未核验",
    "missing_source": "缺来源",
    "expired": "已过期",
}


def prepare_facts_for_generation(
    facts: list[dict[str, Any]],
    *,
    today: date | None = None,
    min_eligible: int = 3,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Filter to publishable evidence for generation.

    Returns ``(eligible_facts, meta)``. Does not raise — caller decides to abort.
    """
    issues = evidence_issues(facts, today=today)
    eligible = eligible_facts(facts, today=today)
    excluded = [
        {
            "id": fact_id,
            "issues": codes,
            "labels": [ISSUE_LABELS.get(c, c) for c in codes],
        }
        for fact_id, codes in sorted(issues.items())
    ]
    ok, message, action = summarize_evidence_blockers(
        facts, today=today, min_eligible=min_eligible
    )
    return eligible, {
        "eligible_count": len(eligible),
        "bound_count": len(facts),
        "min_eligible": min_eligible,
        "ok": ok,
        "message": message,
        "action": action,
        "excluded": excluded,
        "eligible_ids": [f.get("id") for f in eligible if f.get("id") is not None],
    }


def generation_evidence_error_message(meta: dict[str, Any]) -> str:
    """Human-readable 400 body when generation is blocked by evidence."""
    parts = [str(meta.get("message") or "可发布证据不足")]
    excluded = meta.get("excluded") or []
    if excluded:
        detail = "；".join(
            f"#{item.get('id')}({'/'.join(item.get('labels') or item.get('issues') or [])})"
            for item in excluded[:6]
        )
        parts.append(f"已排除：{detail}")
    action = str(meta.get("action") or "").strip()
    if action:
        parts.append(action)
    return "。".join(parts)


def generation_evidence_readiness(facts: list[dict[str, Any]]) -> dict[str, Any]:
    """Editor preview of the same evidence rules enforced before generation.

    This only describes stored facts; it neither verifies nor modifies sources.
    """
    _, meta = prepare_facts_for_generation(facts, min_eligible=3)
    titles = {f.get('id'): f.get('title') or '未命名事实' for f in facts}
    return {**meta,
            'excluded': [{**row, 'title': titles.get(row['id'], '未命名事实')} for row in meta['excluded']],
            'blocking_message': '' if meta['ok'] else generation_evidence_error_message(meta)}
