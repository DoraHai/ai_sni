"""Cross-language evidence helpers that fail closed without a verified translation."""

from __future__ import annotations

import re
from typing import Any


def language(value: str) -> str:
    if re.search(r"[\u4e00-\u9fff]", value or ""):
        return "zh"
    if len(re.findall(r"[A-Za-z]{2,}", value or "")) >= 3:
        return "latin"
    return "unknown"


def verified_translation_texts(fact: dict[str, Any]) -> list[str]:
    """Return only explicit translations tied to the current source statement."""
    trusted = fact.get("_verified_translation_texts")
    if isinstance(trusted, list):
        return [str(value).strip() for value in trusted if str(value).strip()]
    meta = fact.get("meta") if isinstance(fact.get("meta"), dict) else {}
    raw = meta.get("verified_translations") or []
    if isinstance(raw, dict):
        raw = [raw]
    source = str(fact.get("statement") or "").strip()
    result: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        linked_source = str(item.get("source_statement") or "").strip()
        if (
            item.get("status") == "verified"
            and item.get("verified_at")
            and item.get("verified_by") is not None
            and text
            and linked_source == source
            and text not in result
        ):
            result.append(text)
    return result


def _product_phrases(value: str) -> set[str]:
    phrases = re.findall(
        r"(?<![A-Za-z0-9])(?:[A-Z][A-Z0-9®™._+-]{2,})(?:\s+[A-Z][A-Z0-9®™._+-]{1,}){0,3}",
        value or "",
    )
    return {
        re.sub(r"\s+", " ", phrase).replace("®", "").replace("™", "").casefold()
        for phrase in phrases
    }


def _measurements(value: str) -> set[str]:
    result: set[str] = set()
    for number, unit in re.findall(
        r"(?<![A-Za-z0-9])([0-9][0-9,]*(?:\.[0-9]+)?)\s*(%|％|N[·.]?m|kW|W|MPa|kPa|Pa|mm|cm|kg|rpm|r/min|℃|°C)",
        value or "",
        re.I,
    ):
        result.add(
            number.replace(",", "")
            + unit.replace("·", "").replace(".", "").casefold()
        )
    return result


def _shared_anchors(sentence: str, statement: str) -> tuple[int, list[str]]:
    sent_phrases = _product_phrases(sentence)
    fact_phrases = _product_phrases(statement)
    phrase_hits = sent_phrases & fact_phrases
    measure_hits = _measurements(sentence) & _measurements(statement)
    anchors = sorted(phrase_hits | measure_hits)
    phrase_specificity = max((len(p.split()) for p in phrase_hits), default=0)
    return phrase_specificity * 10 + len(measure_hits), anchors


def evidence_candidates(sentence: str, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return traceable retrieval candidates, never semantic approval.

    Language difference by itself is not a relationship. Candidates must share
    a stable product/model phrase or measurement, and only the most specific
    anchor tier is returned.
    """
    source_language = language(sentence)
    if source_language == "unknown":
        return []
    ranked: list[tuple[int, dict[str, Any]]] = []
    for fact in facts or []:
        statement = str(fact.get("statement") or "").strip()
        target_language = language(statement)
        if target_language in {"unknown", source_language}:
            continue
        score, anchors = _shared_anchors(sentence, statement)
        if score <= 0:
            continue
        translations = verified_translation_texts(fact)
        ranked.append(
            (
                score,
                {
                    "fact_id": fact.get("id"),
                    "source_statement": statement,
                    "source_name": fact.get("source_name"),
                    "source_url": fact.get("source_url"),
                    "source_language": target_language,
                    "match_basis": "shared_stable_anchor",
                    "matched_anchors": anchors,
                    "verified_translation": bool(translations),
                    "verified_translation_text": translations[0] if translations else None,
                },
            )
        )
    if not ranked:
        return []
    best = max(score for score, _ in ranked)
    return [item for score, item in ranked if score == best][:3]
