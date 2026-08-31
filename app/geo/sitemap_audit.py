"""Sitemap 全站诊断：抓 sitemap → 抽样审页 → 分类与内容机会。"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from app.urlwords import UA, UrlFetchError, validate_url

_MAX_URLS = 60
_TIMEOUT = 12.0
_SKIP_PATH = re.compile(
    r"/api(?:v\d+)?(?:/|$)|_api(?:/|$)|/openapi|/swagger|/graphql|\.json(?:$|\?)|/v\d+(?:/|$)|/rpc|/internal|/webhook",
    re.I,
)

_TYPE_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("product", re.compile(r"/product|/products|/solutions?|/pricing|/features?|/sku", re.I)),
    ("faq", re.compile(r"/faq|/help|/support|/questions?", re.I)),
    ("case", re.compile(r"/case|/customer|/stories?|/portfolio", re.I)),
    ("about", re.compile(r"/about|/company|/contact", re.I)),
    ("docs", re.compile(r"/docs?|/guide|/wiki|/developer", re.I)),
    ("blog", re.compile(r"/blog|/news|/insight|/article", re.I)),
]


def skip_reason(url: str) -> str | None:
    """Machine/API/intranet URLs should not enter page-type diagnosis."""
    path = urlparse(url).path or ""
    if path.lower().endswith((".xml", ".xml.gz")):
        return "站点地图 XML，不计入 HTML 页面诊断"
    if _SKIP_PATH.search(path):
        return "接口/文档 API 路径，不计入页面类型"
    try:
        validate_url(url)
    except UrlFetchError as exc:
        msg = str(exc)
        if "内网" in msg or "非法" in msg:
            return f"跳过：{msg}"
        return f"跳过：{msg}"
    return None


def classify_path(url: str) -> str:
    path = urlparse(url).path or "/"
    for kind, rx in _TYPE_RULES:
        if rx.search(path):
            return kind
    if path in {"", "/"}:
        return "home"
    return "other"


def collect_robots_sitemaps(robots_text: str) -> list[str]:
    """Keep robots.txt Sitemap: order (do not reverse)."""
    out: list[str] = []
    for line in robots_text.splitlines():
        if line.lower().startswith("sitemap:"):
            loc = line.split(":", 1)[1].strip()
            if loc and loc not in out:
                out.append(loc)
    return out


def _parse_sitemap_locs(xml_text: str) -> list[str]:
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml_text or "", flags=re.I)
    return [u.strip() for u in locs if u.strip().startswith("http")]


async def _fetch_text(url: str) -> str:
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True, headers={"User-Agent": UA}) as http:
        r = await http.get(url)
        r.raise_for_status()
        return r.text[:400_000]


async def discover_sitemap_urls(
    site_url: str,
    *,
    limit: int = _MAX_URLS,
    skip_unusable: bool = False,
) -> tuple[str | None, list[str]]:
    root = validate_url(site_url.strip())
    parsed = urlparse(root)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    default_sitemaps = [urljoin(origin, "/sitemap.xml"), urljoin(origin, "/sitemap_index.xml")]
    robots_sitemaps: list[str] = []
    robots_url = urljoin(origin, "/robots.txt")
    try:
        robots_sitemaps = collect_robots_sitemaps(await _fetch_text(robots_url))
    except Exception:  # noqa: BLE001
        pass
    candidates = robots_sitemaps + [u for u in default_sitemaps if u not in robots_sitemaps]

    seen: list[str] = []
    source = None
    child_cap = 12 if skip_unusable else 6
    for sm in candidates:
        if not sm:
            continue
        try:
            xml = await _fetch_text(sm)
            locs = _parse_sitemap_locs(xml)
        except Exception:  # noqa: BLE001
            continue
        if not locs:
            continue
        source = sm
        # sitemap index → fetch first few children
        if "sitemapindex" in xml.lower() or any(x.endswith(".xml") for x in locs[:3]):
            child_locs: list[str] = []
            for child in locs[:child_cap]:
                try:
                    child_locs.extend(_parse_sitemap_locs(await _fetch_text(child)))
                except Exception:  # noqa: BLE001
                    continue
            locs = child_locs or locs
        for u in locs:
            if skip_unusable and skip_reason(u):
                continue
            if u not in seen:
                seen.append(u)
            if len(seen) >= limit:
                break
        if len(seen) >= limit:
            break
        if seen and not skip_unusable:
            break
    if not seen:
        seen = [origin + "/"]
    return source, seen[:limit]


async def audit_sitemap(site_url: str) -> dict[str, Any]:
    """Return site-wide opportunity list (capped). Does not write tasks."""
    try:
        root = validate_url(site_url.strip())
    except UrlFetchError as exc:
        raise ValueError(str(exc)) from exc

    sitemap_url, urls = await discover_sitemap_urls(root)
    from app.geo.audit import audit_url

    pages: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    type_counts: Counter[str] = Counter()
    for u in urls:
        why = skip_reason(u)
        if why:
            skipped.append({"url": u, "reason": why})
            continue
        kind = classify_path(u)
        type_counts[kind] += 1
        item: dict[str, Any] = {"url": u, "page_type": kind, "ok": False}
        try:
            raw = await audit_url(u)
            item.update(
                {
                    "ok": True,
                    "title": raw.get("title"),
                    "score": raw.get("score"),
                    "schema_types": (raw.get("snapshot") or {}).get("schema_types") or [],
                    "failed_codes": [
                        c.get("code")
                        for c in (raw.get("checks") or [])
                        if not c.get("passed")
                    ][:8],
                }
            )
        except Exception as exc:  # noqa: BLE001
            err = str(exc)[:200]
            if "内网" in err:
                skipped.append({"url": u, "reason": f"跳过：{err}"})
                continue
            item["error"] = err
        pages.append(item)

    content_n = sum(type_counts[t] for t in type_counts if t != "other")
    missing_types: list[str] = []
    if content_n >= 3:
        missing_types = [t for t in ("product", "faq", "case") if type_counts[t] == 0]
    no_schema = [p["url"] for p in pages if p.get("ok") and not p.get("schema_types")]
    low_score = [p for p in pages if isinstance(p.get("score"), (int, float)) and p["score"] < 60]
    title_groups: dict[str, list[str]] = {}
    for p in pages:
        title = str(p.get("title") or "").strip()
        if title:
            title_groups.setdefault(title, []).append(p["url"])
    duplicate_titles = {t: urls for t, urls in title_groups.items() if len(urls) > 1}

    opportunities: list[dict[str, Any]] = []
    for kind in missing_types:
        label = {"product": "产品/方案页", "faq": "FAQ/帮助页", "case": "案例页"}[kind]
        opportunities.append(
            {
                "priority": "high",
                "kind": f"missing_{kind}",
                "title": f"站点缺少{label}",
                "action": f"补一篇可被抽取的{label}，并挂到对应意图词",
            }
        )
    if no_schema:
        opportunities.append(
            {
                "priority": "medium",
                "kind": "missing_schema",
                "title": f"{len(no_schema)} 个页面缺少 JSON-LD",
                "action": "优先给产品页/关于页补 Organization / FAQPage",
                "urls": no_schema[:8],
            }
        )
    for p in low_score[:5]:
        opportunities.append(
            {
                "priority": "medium",
                "kind": "low_score",
                "title": f"低分页面（{p.get('score')}）：{p.get('title') or p['url']}",
                "action": "按单页体检失败项修补后再铺内容",
                "urls": [p["url"]],
            }
        )
    if duplicate_titles:
        first_title, first_urls = next(iter(duplicate_titles.items()))
        opportunities.append(
            {
                "priority": "medium",
                "kind": "duplicate_title",
                "title": f"{len(duplicate_titles)} 组页面标题重复（例：{first_title[:40]}）",
                "action": "合并或改写重复页，避免 AI 抽取到互相冲突的表述",
                "urls": first_urls[:6],
            }
        )
    geo_candidates = [
        p
        for p in pages
        if p.get("ok") and p.get("page_type") in {"product", "faq", "case", "blog", "docs"}
    ]
    for p in geo_candidates[:8]:
        opportunities.append(
            {
                "priority": "low" if p.get("page_type") in {"blog", "docs"} else "medium",
                "kind": "geo_task_candidate",
                "title": f"可转为 GEO 内容任务：{p.get('title') or p['url']}",
                "action": "按该页补一篇可被抽取的问答/对比稿，并挂到对应意图词",
                "urls": [p["url"]],
                "page_type": p.get("page_type"),
            }
        )
    _prio = {"high": 0, "medium": 1, "low": 2}
    opportunities.sort(key=lambda o: _prio.get(str(o.get("priority") or "low"), 9))

    return {
        "site_url": root,
        "sitemap_url": sitemap_url,
        "page_count": len(pages),
        "skipped_count": len(skipped),
        "skipped": skipped[:20],
        "type_counts": dict(type_counts),
        "missing_types": missing_types,
        "sample_note": (
            None
            if content_n >= 3
            else "抽样里可诊断网页太少（多为 API/跳过项），不能据此判断缺少产品页。"
        ),
        "duplicate_title_count": len(duplicate_titles),
        "pages": pages,
        "opportunities": opportunities,
        "priority_summary": {
            "high": sum(1 for o in opportunities if o.get("priority") == "high"),
            "medium": sum(1 for o in opportunities if o.get("priority") == "medium"),
            "low": sum(1 for o in opportunities if o.get("priority") == "low"),
        },
        "note": f"最多抽样 {_MAX_URLS} 个 URL，不是全站穷尽爬取。",
    }
