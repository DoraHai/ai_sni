"""从公开官网提取诊断中心品牌档案候选信息。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.geo.audit import PageDocument, normalize_url, safe_fetch


def website_key(value: str) -> str:
    """用稳定域名作为诊断档案键，不与 SEM 客户主数据混用。"""
    hostname = (urlparse(normalize_url(value)).hostname or "").lower()
    return hostname.removeprefix("www.")


def _schema_nodes(value: Any):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _schema_nodes(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _schema_nodes(nested)


def _clean_name(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" -–—|·_")
    return text[:100]


def _unique(values: list[str], limit: int = 12) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = re.sub(r"\s+", " ", str(value or "")).strip()
        marker = clean.casefold()
        if not clean or marker in seen:
            continue
        seen.add(marker)
        result.append(clean[:180])
        if len(result) >= limit:
            break
    return result


def extract_brand_candidate(document: PageDocument) -> dict[str, Any]:
    soup = BeautifulSoup(document.html, "html.parser")
    schema_nodes: list[dict[str, Any]] = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            import json

            schema_nodes.extend(_schema_nodes(json.loads(node.get_text(strip=True))))
        except (TypeError, ValueError):
            continue

    names: list[tuple[str, str]] = []
    for item in schema_nodes:
        kind = item.get("@type")
        kinds = {str(value).lower() for value in (kind if isinstance(kind, list) else [kind])}
        if kinds & {"organization", "corporation", "brand", "website"} and item.get("name"):
            names.append((_clean_name(item["name"]), "Schema.org"))
    og_site = soup.select_one('meta[property="og:site_name" i]')
    if og_site and og_site.get("content"):
        names.append((_clean_name(str(og_site["content"])), "og:site_name"))
    title = _clean_name(soup.title.get_text(" ", strip=True) if soup.title else "")
    if title:
        names.append((_clean_name(re.split(r"\s+[|｜–—-]\s+", title)[0]), "页面标题"))

    hostname = website_key(document.final_url)
    fallback_name = hostname.split(".")[0].replace("-", " ").title()
    name, name_source = next(((name, source) for name, source in names if name), (fallback_name, "域名"))
    description_node = soup.select_one('meta[name="description" i], meta[property="og:description" i]')
    description = _clean_name(str(description_node.get("content", ""))) if description_node else ""
    headings = _unique(
        [node.get_text(" ", strip=True) for node in soup.select("h1, h2")],
        limit=8,
    )
    schema_industry = next(
        (_clean_name(item.get("industry", "")) for item in schema_nodes if item.get("industry")),
        "",
    )
    schema_offers = _unique(
        [
            str(item.get("name", ""))
            for item in schema_nodes
            if str(item.get("@type", "")).lower() in {"product", "service", "offer"}
        ],
        limit=8,
    )
    return {
        "name": name,
        "website": document.final_url,
        "industry": schema_industry,
        "business_desc": description,
        "brand_terms": _unique([name, fallback_name], limit=6),
        "core_products": schema_offers or headings,
        "proof_points": [],
        "evidence": {
            "name": name_source,
            "business_desc": "Meta Description" if description else "待补充",
            "core_products": "Schema.org" if schema_offers else ("页面 H1/H2" if headings else "待补充"),
        },
        "page_context": {"title": title, "description": description, "headings": headings},
    }


async def discover_brand_profile(website: str) -> dict[str, Any]:
    from app.ai.deepseek import DeepSeekError, chat_json, is_enabled as ai_enabled

    document = await safe_fetch(website)
    candidate = extract_brand_candidate(document)
    ai_used = False
    if ai_enabled():
        context = candidate.pop("page_context")
        try:
            structured = await chat_json(
                "你负责从官网公开信息中整理品牌建档候选值。只使用给定事实，不得虚构。"
                "返回 JSON：name、industry、business_desc、brand_terms、core_products。"
                "brand_terms 和 core_products 必须是字符串数组；不确定的字段返回空值。",
                f"官网：{candidate['website']}\n页面事实：{context}",
                timeout=25,
            )
            for field in ("name", "industry", "business_desc"):
                value = structured.get(field)
                if isinstance(value, str) and value.strip():
                    candidate[field] = value.strip()[:20000 if field == "business_desc" else 100]
                    candidate["evidence"][field] = "AI 整理自官网事实"
            for field in ("brand_terms", "core_products"):
                value = structured.get(field)
                if isinstance(value, list):
                    cleaned = _unique([str(item) for item in value], limit=20)
                    if cleaned:
                        candidate[field] = cleaned
                        candidate["evidence"][field] = "AI 整理自官网事实"
            ai_used = True
        except DeepSeekError:
            candidate["page_context"] = context
    else:
        candidate.pop("page_context", None)
    candidate.pop("page_context", None)
    return {
        "brand": candidate,
        "site_key": website_key(candidate["website"]),
        "ai_used": ai_used,
    }
