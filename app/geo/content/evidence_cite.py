"""Sentence-level fact citations. Appendix is metadata; claims without a fact block ready."""

from __future__ import annotations

import re
from typing import Any

from app.geo.content.fact_retrieve import tokenize

_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")
_APPENDIX = re.compile(r"\n+## 逐句证据\s*\n[\s\S]*\Z")
_PRESENTATION = re.compile(
    r"^\s*(?:#{1,6}\s|[-*+]\s*\*{0,2}(?:问|Q)[：:]|"
    r"(?:行业|受众|内容类型|CTA|建议章节顺序)[：:])",
    re.I,
)


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_SPLIT.split(text or "") if p and p.strip()]
    return [p for p in parts if len(p) >= 8]


def strip_citation_appendix(markdown: str) -> str:
    """Remove a previously appended citation section so repeated saves do not stack it."""
    return _APPENDIX.sub("", markdown or "").rstrip()


def is_presentation_sentence(sentence: str) -> bool:
    value = str(sentence or "").strip()
    return not value or value.endswith(("?", "？")) or bool(_PRESENTATION.search(value))


def _score(sentence: str, fact: dict[str, Any]) -> float:
    q = set(tokenize(sentence))
    from app.geo.content.cross_language import verified_translation_texts

    blob = " ".join(
        [
            str(fact.get("title") or ""),
            str(fact.get("statement") or ""),
            *verified_translation_texts(fact),
        ]
    )
    ftok = set(tokenize(blob))
    if not q or not ftok:
        return 0.0
    hit = q & ftok
    return len(hit) / max(3, len(q))


def _support_basis(sentence: str, fact: dict[str, Any]) -> str | None:
    """Accept only a complete source statement or explicitly verified translation."""
    from app.geo.content.cross_language import verified_translation_texts

    def canonical(value: str) -> str:
        text = re.sub(r"[（(]来源[：:][^）)\n]*[）)]\s*$", "", value or "")
        text = re.sub(r"^\s*(?:#{1,6}|[-*+])\s*", "", text)
        return re.sub(r"[\s*#`]+", "", text).strip("。.!！?？；;").casefold()

    source_values = [str(fact.get("statement") or ""), *verified_translation_texts(fact)]
    sent = canonical(sentence)
    for value in source_values:
        statement = canonical(value)
        if len(statement) >= 4 and statement == sent:
            return "exact_statement"
    return None


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
            ranked = []
            for candidate in facts:
                candidate_score = _score(sent, candidate)
                candidate_basis = _support_basis(sent, candidate)
                ranked.append((candidate_basis is not None, candidate_score, candidate, candidate_basis))
            _supported, score, fact, support_basis = sorted(
                ranked, key=lambda item: (not item[0], -item[1])
            )[0]
            cited = (
                not is_presentation_sentence(sent)
                and score >= min_score
                and support_basis is not None
            )
        else:
            support_basis = None
        is_claim = _sentence_is_claim(sent, facts) or bool(
            not is_presentation_sentence(sent)
            and fact is not None
            and score >= min_score
            and support_basis is None
        )
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
                "support_basis": support_basis if cited else None,
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
