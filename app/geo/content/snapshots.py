"""Visible answer snapshot helpers (Wave B)."""

from __future__ import annotations

VALID_ENGINES = frozenset({"chatgpt", "deepseek", "doubao", "perplexity", "other"})


def clear_brand_missing_tag(tags: list[str] | None) -> list[str]:
    """Remove brand_missing when a snapshot confirms brand mention."""
    if not tags:
        return []
    return [t for t in tags if t != "brand_missing"]


def normalize_cited_urls(raw: list[str] | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for item in raw:
        url = str(item or "").strip()
        if url and url not in out:
            out.append(url[:2000])
    return out[:50]
