"""全站抽样诊断：发现页面、核心页面加权并保留逐页证据。"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from app.geo.audit import GeoAuditError, RULE_WEIGHTS, audit_url, normalize_url, safe_fetch

MAX_SITE_PAGES = 10
MAX_SITEMAPS = 4
PAGE_CONCURRENCY = 3
SKIP_EXTENSIONS = re.compile(
    r"\.(?:jpg|jpeg|png|gif|webp|svg|pdf|zip|rar|mp4|mp3|css|js|xml)$", re.I
)
CORE_PAGE_PATTERN = re.compile(
    r"/(?:products?|services?|solutions?|industr(?:y|ies)|cases?|"
    r"产品|服务|解决方案|行业|案例)(?:/|$)",
    re.I,
)


def _canonical_discovery_url(value: str) -> str:
    parsed = urlparse(value)
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def page_weight(url: str) -> tuple[int, str]:
    path = urlparse(url).path.rstrip("/") or "/"
    leaf = path.rsplit("/", 1)[-1].lower()
    if path == "/" or leaf in {"home", "home.html", "index.html", "index.htm", "default.aspx"}:
        return 3, "首页"
    if CORE_PAGE_PATTERN.search(path):
        return 2, "核心页"
    return 1, "普通页"


def _same_public_site(url: str, hostname: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme in {"http", "https"}
        and (parsed.hostname or "").lower() == hostname.lower()
        and not SKIP_EXTENSIONS.search(parsed.path)
    )


def _xml_locations(xml_text: str) -> tuple[str, list[str]]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return "unknown", []
    root_kind = root.tag.rsplit("}", 1)[-1].lower()
    locations = [
        (node.text or "").strip()
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1].lower() == "loc" and (node.text or "").strip()
    ]
    return root_kind, locations


async def discover_site_urls(url: str, limit: int = MAX_SITE_PAGES) -> tuple[list[str], str]:
    """优先 Sitemap，失败时从首页链接发现；只保留同主机公开 HTML 页面。"""
    requested = normalize_url(url)
    start_document = await safe_fetch(requested)
    final = _canonical_discovery_url(start_document.final_url)
    parsed = urlparse(final)
    hostname = parsed.hostname or ""
    origin = f"{parsed.scheme}://{parsed.netloc}"
    homepage = f"{origin}/"

    sitemap_urls: list[str] = []
    try:
        robots = await safe_fetch(f"{origin}/robots.txt", allow_text=True)
        sitemap_urls.extend(
            match.strip()
            for match in re.findall(r"(?im)^\s*sitemap\s*:\s*(\S+)", robots.html)
        )
    except GeoAuditError:
        pass
    sitemap_urls.append(f"{origin}/sitemap.xml")

    discovered: list[str] = []
    sitemap_queue = list(dict.fromkeys(sitemap_urls))
    visited_sitemaps: set[str] = set()
    while sitemap_queue and len(visited_sitemaps) < MAX_SITEMAPS:
        sitemap_url = sitemap_queue.pop(0)
        if sitemap_url in visited_sitemaps:
            continue
        visited_sitemaps.add(sitemap_url)
        try:
            document = await safe_fetch(sitemap_url, allow_text=True, allow_xml=True)
        except GeoAuditError:
            continue
        kind, locations = _xml_locations(document.html)
        if kind == "sitemapindex":
            sitemap_queue.extend(locations[: MAX_SITEMAPS - len(visited_sitemaps)])
        elif kind == "urlset":
            discovered.extend(locations)

    source = "sitemap" if discovered else "homepage_links"
    if not discovered:
        soup = BeautifulSoup(start_document.html, "html.parser")
        discovered = [
            urljoin(start_document.final_url, str(node.get("href", "")))
            for node in soup.select("a[href]")
        ]

    candidates = [homepage, final, *discovered]
    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = _canonical_discovery_url(candidate)
        if normalized in seen or not _same_public_site(normalized, hostname):
            continue
        seen.add(normalized)
        unique.append(normalized)
    unique.sort(key=lambda item: (-page_weight(item)[0], candidates.index(item) if item in candidates else len(candidates)))
    return unique[: max(1, min(limit, MAX_SITE_PAGES))], source


def aggregate_site_results(
    results: list[dict[str, Any]], *, discovery_source: str, requested_count: int
) -> dict[str, Any]:
    if not results:
        raise GeoAuditError("没有成功完成诊断的站内页面")
    weighted_pages = []
    total_weight = 0
    for result in results:
        weight, page_type = page_weight(result["final_url"])
        total_weight += weight
        weighted_pages.append((result, weight, page_type))

    checks: list[dict[str, Any]] = []
    first_checks = {item["code"]: item for item in results[0]["checks"]}
    for code, template in first_checks.items():
        page_checks = []
        passed_weight = 0
        for result, weight, _ in weighted_pages:
            item = next(row for row in result["checks"] if row["code"] == code)
            if item["passed"]:
                passed_weight += weight
            page_checks.append(
                {
                    "url": result["final_url"],
                    "title": result["title"],
                    "passed": item["passed"],
                    "evidence": item["evidence"],
                }
            )
        pass_rate = passed_weight / max(total_weight, 1)
        passed_pages = sum(1 for item in page_checks if item["passed"])
        checks.append(
            {
                **template,
                "passed": pass_rate == 1,
                "evidence": (
                    f"{passed_pages}/{len(page_checks)} 个页面通过 · "
                    f"核心页面加权通过率 {round(pass_rate * 100)}%"
                ),
                "weight": RULE_WEIGHTS[code],
                "deduction": round(RULE_WEIGHTS[code] * (1 - pass_rate), 1),
                "page_evidence": page_checks,
            }
        )
    score = round(max(0, 100 - sum(item["deduction"] for item in checks)))

    pages = [
        {
            "url": result["final_url"],
            "title": result["title"],
            "score": result["score"],
            "weight": weight,
            "page_type": page_type,
            "passed": result["snapshot"]["passed"],
            "total": result["snapshot"]["total"],
        }
        for result, weight, page_type in weighted_pages
    ]
    union_external_links = sorted(
        {
            link
            for result, _, _ in weighted_pages
            for link in result["snapshot"].get("external_links", [])
        }
    )[:200]
    union_schema_types = sorted(
        {
            schema_type
            for result, _, _ in weighted_pages
            for schema_type in result["snapshot"].get("schema_types", [])
        }
    )
    first = results[0]
    weighted_content = round(
        sum(result["snapshot"].get("content_units", 0) * weight for result, weight, _ in weighted_pages)
        / max(total_weight, 1)
    )
    return {
        "rule_version": first["rule_version"],
        "url": first["url"],
        "final_url": first["final_url"],
        "score": score,
        "title": f"{urlparse(first['final_url']).hostname} 全站诊断（{len(results)}页）",
        "description": "基于核心页面加权的全站抽样诊断。",
        "checks": checks,
        "snapshot": {
            **first["snapshot"],
            "audit_scope": "site",
            "content_units": weighted_content,
            "external_link_count": len(union_external_links),
            "external_links": union_external_links,
            "schema_types": union_schema_types,
            "passed": sum(1 for item in checks if item["passed"]),
            "total": len(checks),
            "site_audit": {
                "discovery_source": discovery_source,
                "requested_pages": requested_count,
                "successful_pages": len(results),
                "page_limit": MAX_SITE_PAGES,
                "total_weight": total_weight,
                "aggregation_method": "首页权重3、产品/服务核心页权重2、其他页面权重1的加权平均。",
                "pages": pages,
            },
        },
    }


def deduplicate_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按抓取后的最终 URL 去重，避免根地址与地区首页重复计权。"""
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for result in results:
        final_url = _canonical_discovery_url(result["final_url"])
        if final_url in seen:
            continue
        seen.add(final_url)
        unique.append(result)
    return unique


async def audit_site(url: str, limit: int = MAX_SITE_PAGES) -> dict[str, Any]:
    urls, source = await discover_site_urls(url, limit=limit)
    semaphore = asyncio.Semaphore(PAGE_CONCURRENCY)

    async def run(page_url: str) -> dict[str, Any] | Exception:
        async with semaphore:
            try:
                return await audit_url(page_url)
            except GeoAuditError as exc:
                return exc

    rows = await asyncio.gather(*(run(page_url) for page_url in urls))
    results = deduplicate_results([row for row in rows if isinstance(row, dict)])
    return aggregate_site_results(
        results,
        discovery_source=source,
        requested_count=len(urls),
    )
