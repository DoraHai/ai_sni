"""Citation accuracy helpers: own-domain + URL reachability heuristics."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from app.geo.content.snapshots import (
    domain_matches,
    extract_cited_domain,
    normalize_citation_accuracy,
    normalize_cited_urls,
)

UA = (
    "Mozilla/5.0 (compatible; GrowthSniper-GEO/1.0; +https://localhost) "
    "AppleWebKit/537.36 Chrome/126 Safari/537.36"
)


def classify_url_vs_own(
    url: str,
    own_domains: list[str] | None,
) -> str:
    """own | external | unknown"""
    domain = extract_cited_domain(url)
    if not domain:
        return "unknown"
    owns = [d for d in (own_domains or []) if d]
    if not owns:
        return "external"
    if any(domain_matches(domain, own) for own in owns):
        return "own"
    return "external"


def suggest_accuracy_from_checks(
    *,
    cited_urls: list[str] | None,
    own_domains: list[str] | None = None,
    url_results: list[dict[str, Any]] | None = None,
) -> str:
    """Heuristic accuracy label from own-domain + reachability checks."""
    urls = normalize_cited_urls(cited_urls)
    if not urls:
        return "unknown"

    results = list(url_results or [])
    if not results:
        # structural only
        kinds = [classify_url_vs_own(u, own_domains) for u in urls]
        if all(k == "own" for k in kinds):
            return "accurate"
        if any(k == "own" for k in kinds):
            return "partial"
        return "unknown"

    ok = 0
    fail = 0
    own_ok = 0
    for r in results:
        status = r.get("status")
        reachable = bool(r.get("reachable"))
        kind = r.get("domain_kind") or "unknown"
        if reachable and isinstance(status, int) and 200 <= status < 400:
            ok += 1
            if kind == "own":
                own_ok += 1
        elif r.get("checked"):
            fail += 1

    if fail and not ok:
        return "inaccurate"
    if ok and fail:
        return "partial"
    if own_ok == len(urls):
        return "accurate"
    if ok == len(urls):
        # all reachable external — cannot verify claim truth → partial
        return "partial"
    if ok:
        return "partial"
    return "unknown"


async def check_cited_urls(
    urls: list[str] | None,
    *,
    own_domains: list[str] | None = None,
    timeout: float = 4.0,
    max_urls: int = 8,
) -> dict[str, Any]:
    """HEAD/GET each URL (capped). Never throws for single URL failures."""
    cited = normalize_cited_urls(urls)[: max(1, min(int(max_urls or 8), 20))]
    items: list[dict[str, Any]] = []
    if not cited:
        return {
            "items": [],
            "suggested_citation_accuracy": "unknown",
            "checked": 0,
            "reachable": 0,
            "own_reachable": 0,
        }

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": UA},
    ) as client:
        for url in cited:
            kind = classify_url_vs_own(url, own_domains)
            entry: dict[str, Any] = {
                "url": url,
                "domain": extract_cited_domain(url),
                "domain_kind": kind,
                "checked": False,
                "reachable": False,
                "status": None,
                "error": None,
            }
            try:
                # Prefer HEAD; some hosts reject → fallback GET
                resp = await client.head(url)
                if resp.status_code in (405, 501, 403) or resp.status_code >= 500:
                    resp = await client.get(url)
                entry["checked"] = True
                entry["status"] = int(resp.status_code)
                entry["reachable"] = 200 <= resp.status_code < 400
                if not entry["reachable"] and resp.status_code in (401, 403):
                    # auth walls still mean the resource exists
                    entry["reachable"] = True
            except Exception as exc:  # noqa: BLE001
                entry["checked"] = True
                entry["error"] = f"{type(exc).__name__}: {exc}"[:200]
            items.append(entry)

    suggested = suggest_accuracy_from_checks(
        cited_urls=cited, own_domains=own_domains, url_results=items
    )
    return {
        "items": items,
        "suggested_citation_accuracy": normalize_citation_accuracy(suggested),
        "checked": sum(1 for i in items if i["checked"]),
        "reachable": sum(1 for i in items if i["reachable"]),
        "own_reachable": sum(
            1 for i in items if i["reachable"] and i["domain_kind"] == "own"
        ),
    }


def strip_url_fragment(url: str) -> str:
    try:
        p = urlparse(url)
        return p._replace(fragment="").geturl()
    except Exception:  # noqa: BLE001
        return url
