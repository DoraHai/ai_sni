"""Rules that decide whether a fact can support publishable content."""

from __future__ import annotations

from datetime import date
from typing import Any


def evidence_issues(facts: list[dict[str, Any]], *, today: date | None = None) -> dict[int, list[str]]:
    reference_date = today or date.today()
    result: dict[int, list[str]] = {}
    for fact in facts:
        fact_id = fact.get("id")
        if fact_id is None:
            continue
        issues: list[str] = []
        if fact.get("status") != "active":
            issues.append("not_active")
        if fact.get("trust_level") != "verified":
            issues.append("not_verified")
        if not str(fact.get("source_name") or "").strip():
            issues.append("missing_source")
        expires_at = fact.get("expires_at")
        if expires_at is not None and expires_at <= reference_date:
            issues.append("expired")
        if issues:
            result[int(fact_id)] = issues
    return result


def eligible_facts(facts: list[dict[str, Any]], *, today: date | None = None) -> list[dict[str, Any]]:
    blocked = evidence_issues(facts, today=today)
    return [fact for fact in facts if fact.get("id") not in blocked]
