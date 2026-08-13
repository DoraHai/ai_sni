"""发布 URL ↔ 监测快照归因：自有域扩展、引用 URL 反查 publication。

闭环证明环节：发了这篇 → 哪次 AI 回答引用了它 → 发布前后提及率变化。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Sequence
from urllib.parse import urlparse, urlunparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo.content.snapshots import extract_cited_domain, normalize_cited_urls
from app.models import (
    GeoAnswerSnapshot,
    GeoChannelVariant,
    GeoContentTask,
    GeoPublication,
)


def normalize_url_for_match(url: str | None) -> str | None:
    """Lowercase host, strip www/fragment/trailing slash, drop default ports."""
    raw = str(url or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    try:
        p = urlparse(raw)
    except ValueError:
        return None
    host = (p.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None
    # Always normalize identity scheme to https so http/https match (W4)
    scheme = "https"
    path = p.path or ""
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    # Drop query/fragment for stable article identity matching
    try:
        port = p.port
    except ValueError:
        port = None
    netloc = host
    # ignore non-default ports only when not 80/443 (already dropped with scheme normalize)
    if port and port not in (80, 443):
        netloc = f"{host}:{port}"
    return urlunparse((scheme, netloc, path or "", "", "", ""))


def urls_match_publication(cited: str | None, published: str | None) -> bool:
    """True when cited URL is the published article or a path under it (or vice versa)."""
    a = normalize_url_for_match(cited)
    b = normalize_url_for_match(published)
    if not a or not b:
        return False
    if a == b:
        return True
    # Same host + one path is prefix of the other (tracking params already stripped)
    pa, pb = urlparse(a), urlparse(b)
    if pa.netloc != pb.netloc:
        return False
    path_a = pa.path or ""
    path_b = pb.path or ""
    if not path_a or not path_b:
        return False
    return path_a.startswith(path_b + "/") or path_b.startswith(path_a + "/")


@dataclass(frozen=True)
class PubRef:
    id: int
    published_url: str
    channel: str
    variant_id: int
    task_id: int
    published_at: datetime | None


async def load_tenant_publications(
    session: AsyncSession, tenant_id: int
) -> list[PubRef]:
    """All publications with URL for a tenant (via variant → task)."""
    stmt = (
        select(
            GeoPublication.id,
            GeoPublication.published_url,
            GeoPublication.channel,
            GeoPublication.variant_id,
            GeoPublication.published_at,
            GeoChannelVariant.task_id,
        )
        .join(GeoChannelVariant, GeoChannelVariant.id == GeoPublication.variant_id)
        .join(GeoContentTask, GeoContentTask.id == GeoChannelVariant.task_id)
        .where(
            GeoContentTask.tenant_id == tenant_id,
            GeoPublication.published_url.is_not(None),
            GeoPublication.published_url != "",
        )
    )
    rows = (await session.execute(stmt)).all()
    out: list[PubRef] = []
    for r in rows:
        url = str(r.published_url or "").strip()
        if not url:
            continue
        out.append(
            PubRef(
                id=int(r.id),
                published_url=url,
                channel=str(r.channel or ""),
                variant_id=int(r.variant_id),
                task_id=int(r.task_id),
                published_at=r.published_at,
            )
        )
    return out


def match_publication_ids(
    cited_urls: Sequence[str] | None,
    pubs: Sequence[PubRef],
) -> list[int]:
    """Return publication ids whose published_url matches any cited URL."""
    urls = normalize_cited_urls(list(cited_urls or []))
    if not urls or not pubs:
        return []
    hits: list[int] = []
    for pub in pubs:
        for u in urls:
            if urls_match_publication(u, pub.published_url):
                if pub.id not in hits:
                    hits.append(pub.id)
                break
    return hits


def domains_from_publications(pubs: Sequence[PubRef]) -> list[str]:
    """Unique domains from publication URLs (first-seen order)."""
    out: list[str] = []
    for pub in pubs:
        d = extract_cited_domain(pub.published_url)
        if d and d not in out:
            out.append(d)
    return out


def merge_domain_lists(*lists: Iterable[str]) -> list[str]:
    out: list[str] = []
    for lst in lists:
        for d in lst or []:
            dd = str(d or "").strip().lower()
            if dd and dd not in out:
                out.append(dd)
    return out


async def resolve_matched_publication_ids(
    session: AsyncSession,
    *,
    tenant_id: int,
    cited_urls: Sequence[str] | None,
    pubs: Sequence[PubRef] | None = None,
) -> list[int]:
    pool = list(pubs) if pubs is not None else await load_tenant_publications(session, tenant_id)
    return match_publication_ids(cited_urls, pool)


def impact_windows(
    published_at: datetime | None,
    *,
    window_days: int = 14,
) -> tuple[datetime | None, datetime | None, datetime | None]:
    """Return (before_start, publish_at, after_end) for pre/post comparison."""
    if published_at is None:
        return None, None, None
    anchor = published_at
    if getattr(anchor, "tzinfo", None) is not None:
        anchor = anchor.replace(tzinfo=None)
    days = max(1, min(int(window_days or 14), 90))
    before_start = anchor - timedelta(days=days)
    after_end = anchor + timedelta(days=days)
    return before_start, anchor, after_end


def rate_or_none(num: int, den: int) -> float | None:
    if den <= 0:
        return None
    return round(num / den, 4)


def summarize_snaps(snaps: Sequence[GeoAnswerSnapshot]) -> dict[str, Any]:
    total = len(snaps)
    mentions = sum(1 for s in snaps if s.mentions_brand)
    return {
        "snapshot_count": total,
        "mention_count": mentions,
        "mention_rate": rate_or_none(mentions, total),
    }
