"""Keyword-based fact retrieval for GEO content tasks (P1a, no embeddings)."""

from __future__ import annotations

import re
from typing import Any

from app.geo.content.brief import normalize_brief

_STOP = {
    "的",
    "了",
    "吗",
    "呢",
    "是",
    "在",
    "和",
    "与",
    "或",
    "及",
    "等",
    "有",
    "哪些",
    "什么",
    "怎么",
    "如何",
    "哪个",
    "哪些",
    "可以",
    "进行",
    "相关",
    "关于",
    "一个",
    "我们",
    "他们",
    "the",
    "a",
    "an",
    "of",
    "and",
    "or",
    "to",
    "for",
    "in",
    "on",
    "is",
    "are",
}


def tokenize(text: str) -> list[str]:
    """Simple CJK/Latin tokens for scoring."""
    raw = (text or "").lower()
    # Latin words + runs of CJK + alnum
    parts = re.findall(r"[a-z0-9]{2,}|[\u4e00-\u9fff]{1,}", raw)
    out: list[str] = []
    for p in parts:
        if p in _STOP:
            continue
        if len(p) == 1 and "\u4e00" <= p <= "\u9fff":
            # keep single CJK only if not stop-like
            out.append(p)
            continue
        if p not in out:
            out.append(p)
    return out


def _fact_type_bonus(fact_type: str | None, intent: str, content_type: str) -> float:
    ft = (fact_type or "").lower()
    bonus = 0.0
    if intent in ("recommend", "compare") and ft in ("product", "case", "metric"):
        bonus += 1.0
    if intent == "risk" and ft in ("policy", "other"):
        bonus += 1.0
    if content_type == "howto" and ft in ("product", "policy"):
        bonus += 0.5
    if content_type == "comparison" and ft in ("product", "metric"):
        bonus += 0.5
    return bonus


def score_fact_against_query(
    fact: dict[str, Any],
    *,
    query_tokens: list[str],
    brief: dict[str, Any] | None = None,
) -> tuple[float, list[str]]:
    """Return (score, reasons)."""
    title = str(fact.get("title") or "")
    statement = str(fact.get("statement") or "")
    source = str(fact.get("source_name") or "")
    title_l = title.lower()
    stmt_l = statement.lower()
    reasons: list[str] = []
    score = 0.0

    for tok in query_tokens:
        t = tok.lower()
        if t in title_l or tok in title:
            score += 3.0
            reasons.append(f"标题命中:{tok}")
        elif t in stmt_l or tok in statement:
            score += 2.0
            reasons.append(f"陈述命中:{tok}")

    data = normalize_brief(brief) if brief else {}
    for term in data.get("must_cover") or []:
        if term and (term in title or term in statement):
            score += 2.0
            reasons.append(f"must_cover:{term}")
    for term in data.get("competitors") or []:
        if term and (term in title or term in statement):
            score += 1.5
            reasons.append(f"竞品相关:{term}")

    intent = data.get("intent") or ""
    content_type = data.get("content_type") or ""
    tb = _fact_type_bonus(fact.get("fact_type"), intent, content_type)
    if tb:
        score += tb
        reasons.append(f"类型加成:{fact.get('fact_type')}")

    if source.strip():
        score += 1.0
        reasons.append("有来源名")
    trust = str(fact.get("trust_level") or "")
    if trust == "verified":
        score += 1.0
        reasons.append("已核验")

    # de-dupe reasons preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    return score, uniq[:12]


def build_query_text(
    *,
    question: str,
    brief: dict[str, Any] | None = None,
) -> str:
    data = normalize_brief(brief) if brief else {}
    parts = [question or ""]
    if data.get("ai_question"):
        parts.append(data["ai_question"])
    parts.extend(data.get("must_cover") or [])
    parts.extend(data.get("competitors") or [])
    parts.extend(data.get("info_gaps") or [])
    if data.get("industry"):
        parts.append(data["industry"])
    return " ".join(str(p) for p in parts if p)


def retrieve_facts(
    facts: list[dict[str, Any]],
    *,
    question: str,
    brief: dict[str, Any] | None = None,
    limit: int = 10,
    verified_only: bool = False,
    max_scan: int = 2000,
) -> dict[str, Any]:
    """Rank tenant facts for a task. Pure function, no IO."""
    limit = max(1, min(int(limit or 10), 50))
    query = build_query_text(question=question, brief=brief)
    tokens = tokenize(query)
    scanned = 0
    scored: list[dict[str, Any]] = []

    for fact in facts:
        if scanned >= max_scan:
            break
        scanned += 1
        if str(fact.get("status") or "active") not in ("active", ""):
            continue
        if verified_only and str(fact.get("trust_level") or "") != "verified":
            continue
        score, reasons = score_fact_against_query(
            fact, query_tokens=tokens, brief=brief
        )
        if score <= 0:
            continue
        scored.append(
            {
                "fact_id": fact.get("id"),
                "score": round(score, 3),
                "reasons": reasons,
                "title": fact.get("title"),
                "trust_level": fact.get("trust_level"),
                "fact_type": fact.get("fact_type"),
                "source_name": fact.get("source_name"),
                "eligible_hint": str(fact.get("trust_level") or "") == "verified",
            }
        )

    scored.sort(key=lambda x: (-float(x["score"]), int(x.get("fact_id") or 0)))
    items = scored[:limit]
    return {
        "items": items,
        "query_meta": {
            "query": query[:500],
            "tokens": tokens[:40],
            "scanned": scanned,
            "matched": len(scored),
            "limit": limit,
            "verified_only": verified_only,
            "algorithm": "keyword_v1",
        },
    }
