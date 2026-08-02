"""Visible answer snapshot helpers (Wave B / B3)."""

from __future__ import annotations

VALID_ENGINES = frozenset({"chatgpt", "deepseek", "doubao", "perplexity", "other"})
VALID_BRAND_POSITIONS = frozenset({"first", "mentioned", "absent", "unknown"})
VALID_SENTIMENTS = frozenset({"positive", "neutral", "negative", "unknown"})


def clear_brand_missing_tag(tags: list[str] | None) -> list[str]:
    """Remove brand_missing when a snapshot confirms brand mention."""
    if not tags:
        return []
    return [t for t in tags if t != "brand_missing"]


def ensure_brand_missing_tag(tags: list[str] | None) -> list[str]:
    """Ensure brand_missing is present when snapshot says brand still missing."""
    out = list(tags or [])
    if "brand_missing" not in out:
        out.append("brand_missing")
    return out


def apply_brand_mention_tags(tags: list[str] | None, *, mentions_brand: bool) -> list[str]:
    if mentions_brand:
        return clear_brand_missing_tag(tags)
    return ensure_brand_missing_tag(tags)


def normalize_cited_urls(raw: list[str] | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for item in raw:
        url = str(item or "").strip()
        if url and url not in out:
            out.append(url[:2000])
    return out[:50]


def normalize_competitors(raw: list[str] | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for item in raw:
        name = str(item or "").strip()[:80]
        if name and name not in out:
            out.append(name)
    return out[:20]


def normalize_brand_position(raw: str | None) -> str:
    value = str(raw or "unknown").strip().lower()
    return value if value in VALID_BRAND_POSITIONS else "unknown"


def normalize_sentiment(raw: str | None) -> str:
    value = str(raw or "unknown").strip().lower()
    return value if value in VALID_SENTIMENTS else "unknown"


def visibility_mention_rate(*, total_snapshots: int, mention_snapshots: int) -> float | None:
    if total_snapshots <= 0:
        return None
    return round(mention_snapshots / total_snapshots, 4)


def needs_recheck(
    *,
    has_published_task: bool,
    task_updated_at,
    last_snapshot_at,
) -> bool:
    """Published content without a snapshot, or snapshot older than last publish update."""
    if not has_published_task:
        return False
    if last_snapshot_at is None:
        return True
    if task_updated_at is None:
        return False
    return last_snapshot_at < task_updated_at
