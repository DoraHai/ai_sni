"""Public-web candidate harvest for competitor placements (not snapshot cites)."""

from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import quote_plus, urlparse

import httpx

from app.geo.content.competitor_placements import inferred_placements_for
from app.urlwords import UA, UrlFetchError, validate_url

_HREF = re.compile(
    r'uddg=([^&"]+)|href="(https?://[^"]+)"[^>]*class="[^"]*result',
    re.I,
)
_TITLE = re.compile(r"<a[^>]+class=\"result__a\"[^>]*>(.*?)</a>", re.I | re.S)
_SKIP_HOST = {
    "duckduckgo.com",
    "bing.com",
    "google.com",
    "baidu.com",
}

_MARKETING_HOSTS = {
    "saasruanjian.com",
    "51cto.com",
    "csdn.net",
    "jianshu.com",
    "sohu.com",
    "toutiao.com",
    "baijiahao.baidu.com",
    "36kr.com",
    "huxiu.com",
    "leiphone.com",
    "itchaguan.com",
    "chinaz.com",
}

_UGC_HOSTS = {
    "zhihu.com",
    "zhuanlan.zhihu.com",
    "weibo.com",
    "tieba.baidu.com",
    "douban.com",
}


def _clean_url(raw: str) -> str | None:
    u = unescape(raw or "").strip()
    if "uddg=" in u:
        from urllib.parse import parse_qs, unquote, urlparse as up

        qs = parse_qs(up(u).query)
        cand = (qs.get("uddg") or [""])[0]
        u = unquote(cand) if cand else u
    if not u.startswith("http"):
        return None
    host = (urlparse(u).hostname or "").lower()
    if any(h in host for h in _SKIP_HOST):
        return None
    try:
        return validate_url(u)
    except UrlFetchError:
        return None


def parse_ddg_html(html: str, query: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for m in _TITLE.finditer(html or ""):
        title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        href_m = re.search(r'href="([^"]+)"', m.group(0))
        href = _clean_url(href_m.group(1) if href_m else "")
        if not href:
            continue
        items.append(
            {
                "url": href,
                "title": title[:160] or href,
                "query": query,
                "source": "web_search",
                "confirmed": False,
            }
        )
        if len(items) >= 5:
            break
    return items


def official_hosts_for(competitor: str) -> set[str]:
    hosts: set[str] = set()
    for p in inferred_placements_for(competitor):
        url = p.get("url")
        if not url:
            continue
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
        if host:
            hosts.add(host)
    return hosts


def _host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _is_lookalike(host: str, official: set[str]) -> bool:
    base = host.split(".")[0].replace("-", "")
    for o in official:
        o_base = o.split(".")[0].replace("-", "")
        if not o_base or host == o or host.endswith("." + o):
            continue
        if base == o_base:
            return True
    return False


def classify_search_url(url: str, official: set[str]) -> dict[str, Any]:
    host = _host_of(url)
    if host in official or any(host.endswith("." + o) for o in official):
        return {
            "trust": "official",
            "risk": "none",
            "label": "官方域名",
        }
    if official and _is_lookalike(host, official):
        return {
            "trust": "lookalike",
            "risk": "high",
            "label": "疑似仿冒/抢注域名",
        }
    if host in _MARKETING_HOSTS or any(host.endswith("." + h) for h in _MARKETING_HOSTS):
        return {
            "trust": "marketing",
            "risk": "medium",
            "label": "营销/目录站，非正式来源",
        }
    if host in _UGC_HOSTS or any(host.endswith("." + h) for h in _UGC_HOSTS):
        return {
            "trust": "ugc",
            "risk": "medium",
            "label": "UGC/评测，需人工确认",
        }
    return {
        "trust": "unknown",
        "risk": "medium",
        "label": "未核验域名",
    }


async def _ddg_html(query: str) -> list[dict[str, Any]]:
    url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True, headers={"User-Agent": UA}) as http:
        r = await http.get(url)
        r.raise_for_status()
        html = r.text[:200_000]
    return parse_ddg_html(html, query)


async def search_competitor_web(competitor: str) -> dict[str, Any]:
    name = (competitor or "").strip()
    if not name:
        raise ValueError("竞品名不能为空")
    queries = [
        f"{name} 官网",
        f"{name} site:zhihu.com",
        f"{name} 客服 评测",
    ]
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for q in queries:
        try:
            for it in await _ddg_html(q):
                if it["url"] in seen:
                    continue
                seen.add(it["url"])
                items.append(it)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{q}: {exc}"[:160])
    official = official_hosts_for(name)
    if not items:
        for p in inferred_placements_for(name):
            url = p.get("url")
            if url and url not in seen:
                items.append(
                    {
                        "url": url,
                        "title": f"{p.get('label') or '官网'}（检索失败，回退已知阵地）",
                        "query": "fallback_known_official",
                        "source": "web_search_fallback",
                        "confirmed": False,
                    }
                )
    labeled: list[dict[str, Any]] = []
    for it in items[:12]:
        trust = classify_search_url(it["url"], official)
        labeled.append({**it, **trust})
    return {
        "competitor": name,
        "items": labeled,
        "official_hosts": sorted(official),
        "query_count": len(queries),
        "errors": errors,
        "note": "外部检索候选，不是本次 AI 回答的 cited_urls。需人工确认后才能写入报告。仿冒域名与营销软文已单独标记，默认不要当官方来源。",
    }
