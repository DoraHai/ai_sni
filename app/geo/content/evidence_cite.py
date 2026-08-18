"""Sentence-level fact citations. Appendix is metadata; claims without a fact block ready."""

from __future__ import annotations

import re
from typing import Any

from app.geo.content.fact_retrieve import tokenize

_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")
_APPENDIX = re.compile(r"\n+## 逐句证据\s*\n[\s\S]*\Z")


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_SPLIT.split(text or "") if p and p.strip()]
    return [p for p in parts if len(p) >= 8 and not p.startswith("#") and not p.startswith("*")]


def strip_citation_appendix(markdown: str) -> str:
    """Remove a previously appended 「逐句证据」 section so re-cite does not stack."""
    return _APPENDIX.sub("", markdown or "").rstrip()


def _score(sentence: str, fact: dict[str, Any]) -> float:
    q = set(tokenize(sentence))
    blob = f"{fact.get('title') or ''} {fact.get('statement') or ''}"
    ftok = set(tokenize(blob))
    if not q or not ftok:
        return 0.0
    hit = q & ftok
    return len(hit) / max(3, min(len(q), 12))


def _sentence_is_claim(sentence: str, facts: list[dict[str, Any]]) -> bool:
    from app.geo.content.claim_guard import ungrounded_claims

    return bool(ungrounded_claims(sentence, facts))


def build_sentence_citations(
    markdown: str, facts: list[dict[str, Any]], *, min_score: float = 0.22
) -> list[dict[str, Any]]:
    """Match sentences to facts. Does not invent facts or rewrite the body."""
    facts = [f for f in facts or [] if f.get("id") is not None]
    body = strip_citation_appendix(markdown)
    rows: list[dict[str, Any]] = []
    if not body.strip():
        return rows
    for sent in split_sentences(body)[:40]:
        cited = False
        fact: dict[str, Any] | None = None
        score = 0.0
        if facts:
            ranked = sorted(((_score(sent, f), f) for f in facts), key=lambda x: -x[0])
            score, fact = ranked[0]
            cited = score >= min_score
        is_claim = _sentence_is_claim(sent, facts)
        needs_fact = (not cited) and is_claim
        rows.append(
            {
                "sentence": sent[:180],
                "fact_id": fact.get("id") if cited and fact else None,
                "fact_title": fact.get("title") if cited and fact else None,
                "source_name": fact.get("source_name") if cited and fact else None,
                "score": round(score, 3),
                "cited": cited,
                "is_claim": is_claim,
                "needs_fact": needs_fact,
            }
        )
    return rows


def format_citation_appendix(rows: list[dict[str, Any]]) -> str:
    cited_n = sum(1 for r in rows if r.get("cited"))
    block_n = sum(1 for r in rows if r.get("needs_fact"))
    lines = [
        "",
        "## 逐句证据",
        "",
        f"已挂事实 {cited_n}/{len(rows)} 句；主张未挂 {block_n} 句（须删改或补核验事实）。",
        "",
    ]
    for i, r in enumerate(rows, 1):
        sent = (r.get("sentence") or "")[:80]
        if r.get("cited"):
            lines.append(
                f"{i}. {sent}… → 事实卡 #{r.get('fact_id')}「{r.get('fact_title')}」"
                f"（{r.get('source_name') or '来源未填'}）"
            )
        elif r.get("needs_fact"):
            lines.append(f"{i}. {sent}… → **主张未挂事实，阻断就绪**")
        else:
            lines.append(f"{i}. {sent}… → 叙述句，可不挂")
    lines.append("")
    return "\n".join(lines)


def attach_sentence_citations(
    markdown: str, facts: list[dict[str, Any]], *, min_score: float = 0.22
) -> tuple[str, list[dict[str, Any]]]:
    """Return (body without stacked appendix, citation rows)."""
    body = strip_citation_appendix(markdown)
    rows = build_sentence_citations(body, facts, min_score=min_score)
    return body, rows


def citation_verdict(rows: list[dict[str, Any]]) -> dict[str, Any]:
    blocking = [r for r in rows if r.get("needs_fact")]
    cited = sum(1 for r in rows if r.get("cited"))
    return {
        "total": len(rows),
        "cited": cited,
        "blocking": len(blocking),
        "ok": not blocking,
    }
