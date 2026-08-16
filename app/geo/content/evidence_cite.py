"""Attach per-sentence fact citations to generated markdown."""

from __future__ import annotations

import re
from typing import Any

from app.geo.content.fact_retrieve import tokenize

_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_SPLIT.split(text or "") if p and p.strip()]
    return [p for p in parts if len(p) >= 8 and not p.startswith("#") and not p.startswith("*")]


def _score(sentence: str, fact: dict[str, Any]) -> float:
    q = set(tokenize(sentence))
    blob = f"{fact.get('title') or ''} {fact.get('statement') or ''}"
    ftok = set(tokenize(blob))
    if not q or not ftok:
        return 0.0
    hit = q & ftok
    return len(hit) / max(3, min(len(q), 12))


def attach_sentence_citations(
    markdown: str, facts: list[dict[str, Any]], *, min_score: float = 0.22
) -> tuple[str, list[dict[str, Any]]]:
    """Return (markdown + appendix, citation rows). Does not invent facts."""
    facts = [f for f in facts or [] if f.get("id") is not None]
    rows: list[dict[str, Any]] = []
    if not facts:
        return markdown, rows
    for sent in split_sentences(markdown)[:40]:
        ranked = sorted(
            ((_score(sent, f), f) for f in facts),
            key=lambda x: -x[0],
        )
        score, fact = ranked[0]
        cited = score >= min_score
        rows.append(
            {
                "sentence": sent[:180],
                "fact_id": fact.get("id") if cited else None,
                "fact_title": fact.get("title") if cited else None,
                "source_name": fact.get("source_name") if cited else None,
                "score": round(score, 3),
                "cited": cited,
            }
        )
    cited_n = sum(1 for r in rows if r["cited"])
    appendix = [
        "",
        "## 逐句证据",
        "",
        f"已为 {cited_n}/{len(rows)} 句挂上事实卡。未挂上的句子需人工核对，不得当成已核验。",
        "",
    ]
    for i, r in enumerate(rows, 1):
        if r["cited"]:
            appendix.append(
                f"{i}. {r['sentence'][:80]}… → 事实卡 #{r['fact_id']}「{r['fact_title']}」"
                f"（{r.get('source_name') or '来源未填'}）"
            )
        else:
            appendix.append(f"{i}. {r['sentence'][:80]}… → **未挂事实，需人工核验**")
    appendix.append("")
    return (markdown or "").rstrip() + "\n" + "\n".join(appendix), rows
