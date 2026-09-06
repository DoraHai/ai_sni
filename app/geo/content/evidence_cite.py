"""Sentence-level fact citations. Appendix is metadata; claims without a fact block ready."""

from __future__ import annotations

import re
from typing import Any

from app.geo.content.fact_retrieve import tokenize

_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")
_APPENDIX = re.compile(r"\n+## 逐句证据\s*\n[\s\S]*\Z")


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_SPLIT.split(text or "") if p and p.strip()]
    return [p for p in parts if len(p) >= 8]


def strip_citation_appendix(markdown: str) -> str:
    """Remove a previously appended citation section so repeated saves do not stack it."""
    return _APPENDIX.sub("", markdown or "").rstrip()


def _score(sentence: str, fact: dict[str, Any]) -> float:
    q = set(tokenize(sentence))
    blob = f"{fact.get('title') or ''} {fact.get('statement') or ''}"
    ftok = set(tokenize(blob))
    if not q or not ftok:
        return 0.0
    hit = q & ftok
    return len(hit) / max(3, len(q))


def _sentence_is_claim(sentence: str, facts: list[dict[str, Any]]) -> bool:
    from app.geo.content.claim_guard import ungrounded_claims

    return bool(ungrounded_claims(sentence, facts))


def build_sentence_citations(
    markdown: str, facts: list[dict[str, Any]], *, min_score: float = 0.22
) -> list[dict[str, Any]]:
    """Match sentences to facts without inventing facts or rewriting the body."""
    facts = [f for f in facts or [] if f.get("id") is not None]
    body = strip_citation_appendix(markdown)
    rows: list[dict[str, Any]] = []
    if not body.strip():
        return rows
    for sent in split_sentences(body):
        cited = False
        fact: dict[str, Any] | None = None
        score = 0.0
        if facts:
            ranked = sorted(((_score(sent, f), f) for f in facts), key=lambda x: -x[0])
            score, fact = ranked[0]
            cited = score >= min_score
        is_claim = _sentence_is_claim(sent, facts)
        # Similarity is only a retrieval hint. It cannot override a known
        # unsupported assertion, even when the rest repeats a fact verbatim.
        if is_claim:
            cited = False
        from app.geo.content.cross_language import evidence_candidates
        candidates = evidence_candidates(sent, facts) if is_claim else []
        rows.append(
            {
                "sentence": sent[:180],
                "fact_id": fact.get("id") if cited and fact else None,
                "fact_title": fact.get("title") if cited and fact else None,
                "source_name": fact.get("source_name") if cited and fact else None,
                "score": round(score, 3),
                "cited": cited,
                "is_claim": is_claim,
                "needs_fact": is_claim,
                "review_status": "needs_review" if is_claim else "not_required",
                "review_reason": "cross_language_unverified" if candidates else ("unsupported_claim" if is_claim else None),
                "evidence_candidates": candidates,
            }
        )
    return rows


def format_citation_appendix(rows: list[dict[str, Any]]) -> str:
    cited_n = sum(1 for r in rows if r["cited"])
    blocking_n = sum(1 for r in rows if r.get("needs_fact"))
    appendix = [
        "",
        "## 逐句证据",
        "",
        f"已挂事实 {cited_n}/{len(rows)} 句；主张未挂 {blocking_n} 句（须删改或补核验事实）。",
        "",
    ]
    for i, r in enumerate(rows, 1):
        if r["cited"]:
            appendix.append(
                f"{i}. {r['sentence'][:80]}… → 事实卡 #{r['fact_id']}「{r['fact_title']}」"
                f"（{r.get('source_name') or '来源未填'}）"
            )
        elif r.get("needs_fact"):
            appendix.append(f"{i}. {r['sentence'][:80]}… → **主张未挂事实，阻断就绪**")
        else:
            appendix.append(f"{i}. {r['sentence'][:80]}… → 叙述句，可不挂")
    appendix.append("")
    return "\n".join(appendix)


def attach_sentence_citations(
    markdown: str, facts: list[dict[str, Any]], *, min_score: float = 0.22
) -> tuple[str, list[dict[str, Any]]]:
    """Return a de-duplicated body and its structured citation metadata."""
    body = strip_citation_appendix(markdown)
    return body, build_sentence_citations(body, facts, min_score=min_score)


def citation_verdict(rows: list[dict[str, Any]]) -> dict[str, Any]:
    blocking = [row for row in rows if row.get("needs_fact")]
    cited = sum(1 for row in rows if row.get("cited"))
    return {
        "total": len(rows),
        "cited": cited,
        "blocking": len(blocking),
        "ok": not blocking,
    }
