"""GEO report calculations over stored evidence; no sampling or remote calls."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from app.geo.content.sample_provenance import sample_provenance

SHANGHAI = ZoneInfo("Asia/Shanghai")
TRACKING = {"spm", "from"}


def local_time(value: datetime) -> datetime:
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).astimezone(SHANGHAI)


def provenance(row) -> str:
    kind = sample_provenance(row)["sample_kind"]
    # Single probe drafts are persisted through the operator POST, whose
    # sample_mode can be supplied by the caller.  Only a server-owned patrol
    # run is durable proof that an engine response was actually collected.
    if kind == "real" and getattr(row, "patrol_run_id", None) is None:
        return "unknown"
    return kind


def normalize_report_url(value: str | None) -> str | None:
    """Preserve scheme and meaningful query fields for exact article identity."""
    try:
        p = urlsplit(str(value or "").strip())
        host = (p.hostname or "").lower().rstrip(".")
        if p.scheme.lower() not in {"http", "https"} or not host or any(ord(c) < 33 for c in host):
            return None
        port = p.port
        netloc = host if port is None or (p.scheme.lower(), port) in {("http", 80), ("https", 443)} else f"{host}:{port}"
        query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                               if k.lower() not in TRACKING and not k.lower().startswith("utm_")))
        return urlunsplit((p.scheme.lower(), netloc, p.path.rstrip("/") or "/", query, ""))
    except ValueError:
        return None


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


def _registrable(host: str) -> str:
    # A conservative common-suffix approximation; no external suffix database is needed.
    parts = host.split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in {"co", "com", "net", "org", "gov", "edu", "ac", "ne", "or", "go"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def citation_match(published: str, cited_urls: list[str] | None, answer: str = "") -> tuple[str | None, str | None]:
    target = normalize_report_url(published)
    if not target:
        return None, None
    loose = None
    tp = urlsplit(target)
    for raw in cited_urls or []:
        cited = normalize_report_url(raw)
        if not cited:
            continue
        if cited == target:
            return "exact", raw
        cp = urlsplit(cited)
        if _registrable(_host(target)) == _registrable(_host(cited)):
            a, b = tp.path.rstrip("/"), cp.path.rstrip("/")
            if (a and b and (a == b or a.startswith(b + "/") or b.startswith(a + "/"))) or _host(target) == _host(cited):
                loose = raw
    if loose:
        return "loose", loose
    if published in (answer or "") or target in (answer or ""):
        return "loose", published
    return None, None


def trend_rows(snapshots, prompts, start: date, end: date, granularity: str, sample_kind: str = "real", engines=None) -> list[dict]:
    if granularity not in {"day", "week", "month"}:
        raise ValueError("粒度只能是 day、week 或 month")
    groups = defaultdict(lambda: [0, 0])
    engines = {str(s.engine) for s in snapshots} | {str(e) for e in (engines or [])}
    cursor = start
    buckets = []
    while cursor <= end:
        if granularity == "day":
            key, next_day = cursor.isoformat(), cursor + timedelta(days=1)
        elif granularity == "week":
            iso = cursor.isocalendar()
            key, next_day = f"{iso.year}-W{iso.week:02d}", cursor + timedelta(days=7 - cursor.weekday())
        else:
            key = cursor.strftime("%Y-%m")
            next_day = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        if key not in buckets:
            buckets.append(key)
        cursor = next_day
    for s in snapshots:
        d = local_time(s.captured_at).date()
        if d < start or d > end or provenance(s) != sample_kind or getattr(prompts.get(s.prompt_id), "is_brand_probe", False):
            continue
        iso = d.isocalendar()
        key = d.isoformat() if granularity == "day" else (f"{iso.year}-W{iso.week:02d}" if granularity == "week" else d.strftime("%Y-%m"))
        pair = groups[(str(s.engine), key)]
        pair[0] += int(bool(s.mentions_brand))
        pair[1] += 1
    return [{"engine": engine, "bucket": bucket, "mentions": groups[(engine, bucket)][0],
             "samples": groups[(engine, bucket)][1],
             "rate": (groups[(engine, bucket)][0] / groups[(engine, bucket)][1] if groups[(engine, bucket)][1] else None)}
            for engine in sorted(engines) for bucket in buckets]


def citation_rows(publications, snapshots, start: date, end: date, sample_kind: str = "real", publication_checks=None) -> list[dict]:
    result = []
    for pub in publications:
        matches = []
        for snap in snapshots:
            day = local_time(snap.captured_at).date()
            if not start <= day <= end or provenance(snap) != sample_kind:
                continue
            kind, matched_url = citation_match(pub.published_url, snap.cited_urls, snap.raw_text)
            if kind:
                matches.append({"sample_id": snap.id, "engine": snap.engine, "date": day.isoformat(),
                                "kind": kind, "matched_url": matched_url})
        result.append({"publication_id": pub.id, "task_id": pub.task_id, "channel": pub.channel,
                       "published_url": pub.published_url, "published_at": pub.published_at.isoformat() if pub.published_at else None,
                       "exact_count": sum(m["kind"] == "exact" for m in matches),
                       "loose_count": sum(m["kind"] == "loose" for m in matches), "matches": matches,
                       "source_verification": (publication_checks or {}).get(pub.id, {
                           "state": "unverified", "verified": False, "citation_accuracy": "not_evaluated"})})
    return result
