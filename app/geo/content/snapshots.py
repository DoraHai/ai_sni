"""Visible answer snapshot helpers (Wave B / B3 / citation insights)."""

from __future__ import annotations

import re
from urllib.parse import urlparse

VALID_ENGINES = frozenset({"chatgpt", "deepseek", "doubao", "perplexity", "other"})
VALID_BRAND_POSITIONS = frozenset({"first", "mentioned", "absent", "unknown"})
VALID_SENTIMENTS = frozenset({"positive", "neutral", "negative", "unknown"})

# Prefer explicit http(s) links; keep URL charset tight so CJK prose does not stick.
_URL_IN_TEXT = re.compile(
    r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+",
    re.I,
)
_URL_TRAIL_PUNCT = ")]}>.,;:\"'"


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


def extract_cited_domain(url: str | None) -> str | None:
    """Return hostname without leading www; None when unparseable."""
    raw = str(url or "").strip()
    if not raw or any(ch.isspace() for ch in raw):
        return None
    if "://" not in raw:
        raw = "https://" + raw
    try:
        host = urlparse(raw).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host or any(ch.isspace() for ch in host):
        return None
    # Reject obvious non-host tokens (urlparse is permissive).
    if any(ch in host for ch in (":", "/", "?", "#")):
        return None
    return host[:253]


def extract_cited_domains(urls: list[str] | None) -> list[str]:
    """Unique domains in first-seen order from cited URL list."""
    out: list[str] = []
    for url in urls or []:
        domain = extract_cited_domain(url)
        if domain and domain not in out:
            out.append(domain)
    return out


def extract_cited_urls_from_text(text: str | None) -> list[str]:
    """Pull http(s) URLs out of pasted/probe answer text for operator confirm."""
    body = str(text or "")
    if not body.strip():
        return []
    found: list[str] = []
    for match in _URL_IN_TEXT.finditer(body):
        url = match.group(0).rstrip(_URL_TRAIL_PUNCT)
        while len(url) > 8 and url[-1] in ")]}":
            closer = url[-1]
            opener = {")": "(", "]": "[", "}": "{"}[closer]
            if url.count(opener) >= url.count(closer):
                break
            url = url[:-1].rstrip(_URL_TRAIL_PUNCT)
        if extract_cited_domain(url) and url not in found:
            found.append(url[:2000])
        if len(found) >= 50:
            break
    return found


def domain_matches(domain: str, candidate: str) -> bool:
    """True when domain equals candidate or is a subdomain of it."""
    d = (domain or "").lower().strip(".")
    c = (candidate or "").lower().strip(".")
    if not d or not c:
        return False
    return d == c or d.endswith("." + c)


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
    """Category visibility rate. Return None when unmeasured (never fake 0)."""
    if total_snapshots <= 0:
        return None
    return round(mention_snapshots / total_snapshots, 4)


def split_visibility_metrics(
    rows: list[dict],
) -> dict[str, float | int | None]:
    """Split snapshots into visibility vs brand-probe buckets (GeoLook D0).

    Each row: ``{mentions_brand: bool, is_brand_probe: bool}``.
    Probe answers nearly always echo the brand name and must not inflate
    category visibility mention_rate.
    """
    visibility = [r for r in rows if not r.get("is_brand_probe")]
    probe = [r for r in rows if r.get("is_brand_probe")]
    vis_n = len(visibility)
    probe_n = len(probe)
    vis_hit = sum(1 for r in visibility if r.get("mentions_brand"))
    probe_hit = sum(1 for r in probe if r.get("mentions_brand"))
    return {
        "snapshots_visibility": vis_n,
        "snapshots_visibility_mention": vis_hit,
        "visibility_mention_rate": visibility_mention_rate(
            total_snapshots=vis_n, mention_snapshots=vis_hit
        ),
        "snapshots_probe": probe_n,
        "snapshots_probe_mention": probe_hit,
        "probe_recognition_rate": visibility_mention_rate(
            total_snapshots=probe_n, mention_snapshots=probe_hit
        ),
    }


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
