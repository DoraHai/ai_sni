"""官网结构扫描：抽样页面 JSON-LD，映射成可实施的 Schema 建议。"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.geo.audit import _json_ld_items, _schema_types, safe_fetch
from app.geo.sitemap_audit import classify_path, discover_sitemap_urls, skip_reason

MAX_PAGES = 24
_CONCURRENCY = 6
_PICK_KIND_ORDER = (
    "home",
    "about",
    "product",
    "service",
    "faq",
    "blog",
    "case",
    "docs",
    "other",
)
_KIND_CN = {
    "home": "品牌页面",
    "about": "品牌页面",
    "product": "产品",
    "service": "服务",
    "faq": "FAQ",
    "blog": "文章",
    "docs": "文章",
    "case": "文章",
    "other": "其他",
}
_EXPECTED = {
    "品牌页面": ("Organization", "WebSite"),
    "产品": ("Product",),
    "服务": ("Service",),
    "FAQ": ("FAQPage",),
    "文章": ("Article",),
    "其他": (),
}


def page_kind(url: str) -> str:
    path = urlparse(url).path or "/"
    if re.search(r"/services?(/|$)|/service/", path, re.I):
        return "service"
    return classify_path(url)


def page_type_cn(url: str) -> str:
    return _KIND_CN.get(page_kind(url), "其他")


def _path_of(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return path


def _scan_url_key(url: str) -> str:
    """Normalize equivalent home URLs before building the scan sample."""
    parsed = urlparse(url)
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    return parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        path=path,
        fragment="",
    ).geturl()


def _first_str(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("name") or value.get("text") or value.get("url") or value.get("@id") or "").strip()
    if isinstance(value, list) and value:
        return _first_str(value[0])
    return ""


def _collect_same_as(items: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    queue: list[Any] = list(items)
    while queue:
        item = queue.pop()
        if not isinstance(item, dict):
            continue
        graph = item.get("@graph")
        if isinstance(graph, list):
            queue.extend(graph)
        raw = item.get("sameAs")
        values = raw if isinstance(raw, list) else [raw] if raw else []
        for val in values:
            text = _first_str(val)
            if text and text not in out:
                out.append(text)
    return out


def _has_about_product(items: list[dict[str, Any]]) -> bool:
    queue: list[Any] = list(items)
    while queue:
        item = queue.pop()
        if not isinstance(item, dict):
            continue
        graph = item.get("@graph")
        if isinstance(graph, list):
            queue.extend(graph)
        about = item.get("about") or item.get("mentions")
        blob = about if isinstance(about, list) else [about]
        for node in blob:
            if not isinstance(node, dict):
                continue
            kind = node.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            if any(str(k) == "Product" for k in kinds if k):
                return True
    return False


def _schema_nodes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    queue: list[Any] = list(items)
    while queue:
        item = queue.pop()
        if not isinstance(item, dict):
            continue
        nodes.append(item)
        graph = item.get("@graph")
        if isinstance(graph, list):
            queue.extend(graph)
    return nodes


def _has_schema_type(node: dict[str, Any], schema_type: str) -> bool:
    value = node.get("@type")
    values = value if isinstance(value, list) else [value]
    return schema_type in {str(item) for item in values if item}


def _valid_schema_types(items: list[dict[str, Any]]) -> set[str]:
    """Return declared schema types that include their minimum useful fields."""
    valid: set[str] = set()
    for node in _schema_nodes(items):
        if _has_schema_type(node, "Organization") and _first_str(node.get("name")) and _first_str(node.get("url")):
            valid.add("Organization")
        if _has_schema_type(node, "WebSite") and _first_str(node.get("name")) and _first_str(node.get("url")):
            valid.add("WebSite")
        if _has_schema_type(node, "Product") and _first_str(node.get("name")) and _first_str(node.get("url")) and _first_str(node.get("brand")):
            valid.add("Product")
        if _has_schema_type(node, "Service") and _first_str(node.get("name")) and _first_str(node.get("url")) and _first_str(node.get("provider")):
            valid.add("Service")
        if _has_schema_type(node, "Article") and _first_str(node.get("headline")) and _first_str(node.get("url")) and (_first_str(node.get("author")) or _first_str(node.get("publisher"))):
            valid.add("Article")
        if _has_schema_type(node, "FAQPage"):
            entities = node.get("mainEntity")
            entries = entities if isinstance(entities, list) else [entities]
            if any(isinstance(entry, dict) and _first_str(entry.get("name")) and _first_str(entry.get("acceptedAnswer")) for entry in entries):
                valid.add("FAQPage")
    return valid


def suggest_jsonld(
    *,
    page_type: str,
    url: str,
    title: str,
    brand: str,
    summary: str,
    questions: list[str],
    same_as: list[str],
) -> dict[str, Any]:
    origin = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    name = title or brand or origin
    if page_type == "产品":
        payload: dict[str, Any] = {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": name,
            "url": url,
        }
        if brand:
            payload["brand"] = {"@type": "Brand", "name": brand}
        if summary:
            payload["description"] = summary
        return payload
    if page_type == "服务":
        payload = {
            "@context": "https://schema.org",
            "@type": "Service",
            "name": name,
            "url": url,
        }
        if brand:
            payload["provider"] = {"@type": "Organization", "name": brand}
        return payload
    if page_type == "FAQ":
        entity = [{"@type": "Question", "name": q} for q in questions[:8]]
        return {"@context": "https://schema.org", "@type": "FAQPage", "url": url, "mainEntity": entity}
    if page_type == "文章":
        payload = {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": name,
            "url": url,
        }
        if brand:
            payload["publisher"] = {"@type": "Organization", "name": brand}
        return payload
    payload = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": brand or name,
        "url": origin,
    }
    if same_as:
        payload["sameAs"] = same_as
    return payload


def _status_for(page_type: str, types: set[str], valid_types: set[str], *, has_author: bool, same_as: list[str]) -> tuple[str, str, str]:
    expected = _EXPECTED.get(page_type, ())
    missing = [t for t in expected if t not in valid_types]
    if page_type == "其他":
        if types:
            if not valid_types:
                return "可增强", "已识别 Schema，但缺少关键字段", "P3"
            return "正常", "—", "P3"
        return "可增强", "未识别结构化数据", "P3"
    if missing:
        incomplete = [t for t in missing if t in types]
        if incomplete:
            return "可增强", f"{' / '.join(incomplete)} 缺少关键字段", "P2"
        return "缺失", f"缺少 {' / '.join(missing)}", "P1" if page_type in {"产品", "FAQ", "品牌页面"} else "P2"
    if page_type == "文章" and "Person" not in types and not has_author:
        return "可增强", "缺少 author", "P2"
    if page_type == "品牌页面" and ("Organization" in types or "Brand" in types) and not same_as:
        return "可增强", "缺少 sameAs", "P2"
    if "Offer" in types and "Product" in types:
        return "正常", "—", "P3"
    return "正常", "—", "P3"


def build_page_row(
    *,
    url: str,
    title: str,
    types: list[str],
    h1s: list[str],
    has_author: bool,
    has_date: bool,
    questions: list[str],
    same_as: list[str],
    about_product: bool,
    items: list[dict[str, Any]],
    brand: str,
    summary: str,
    error: str | None = None,
) -> dict[str, Any]:
    page_type = page_type_cn(url)
    type_set = set(types)
    valid_type_set = _valid_schema_types(items)
    if error:
        status, issue, pri = "错误", error[:80], "P2"
    else:
        status, issue, pri = _status_for(page_type, type_set, valid_type_set, has_author=has_author, same_as=same_as)
    expected = _EXPECTED.get(page_type, ())
    structures = [[t, t in type_set] for t in (list(expected) + [x for x in types if x not in expected])]
    detected = []
    if brand:
        detected.append(["品牌", brand])
    if title:
        detected.append(["页面标题", title])
    if h1s:
        detected.append(["H1", h1s[0]])
    if questions:
        detected.append(["问答", f"{len(questions)} 组"])
    schema = ", ".join(types) if types else "无"
    suggest = " / ".join(expected) if expected else "维持现有结构"
    jsonld = suggest_jsonld(
        page_type=page_type,
        url=url,
        title=title or (h1s[0] if h1s else ""),
        brand=brand,
        summary=summary,
        questions=questions,
        same_as=same_as,
    )
    fields = [
        {"key": "name", "value": (brand if page_type == "品牌页面" else title) or brand, "source": "品牌信息" if page_type == "品牌页面" and brand else "页面标题 / 品牌信息"},
        {"key": "url", "value": _path_of(url), "source": "当前 URL"},
    ]
    if brand:
        fields.insert(1, {"key": "brand", "value": brand, "source": "品牌信息"})
    problem = (
        error
        or (f"{issue}。页面已有内容，但缺少标准化实体表达。" if status == "缺失" else "")
        or (f"{issue}。建议补齐字段后再发布。" if status == "可增强" else "")
        or "Schema 有效，并与页面内容一致。"
    )
    improves = []
    if "Product" in expected:
        improves += ["产品实体表达", "品牌归属关系"]
    if "FAQPage" in expected:
        improves += ["问题—答案关系"]
    if "Article" in expected:
        improves += ["作者实体", "内容来源关系"]
    if "Organization" in expected:
        improves += ["品牌实体", "官方账号关系"]
    return {
        "id": _path_of(url),
        "name": title or _path_of(url),
        "url": _path_of(url),
        "full_url": url,
        "type": page_type,
        "schema": schema,
        "schema_types": types,
        "valid_schema_types": sorted(valid_type_set),
        "status": status,
        "issue": issue,
        "pri": pri,
        "title": title,
        "detected": detected,
        "structures": structures,
        "problem": problem,
        "suggest": suggest,
        "improves": improves or ["保持现有结构"],
        "jsonld": jsonld,
        "fields": fields,
        "has_author": has_author,
        "has_date": has_date,
        "questions": questions,
        "same_as": same_as,
        "about_product": about_product,
        "json_ld_count": len(items),
    }


def _pct(have: int, total: int) -> int | None:
    if total <= 0:
        return None
    return round(100 * have / total)


def _badge(pct: int | None, *, empty: str = "未发现") -> tuple[str, str]:
    if pct is None:
        return empty, "amber"
    if pct >= 80:
        return "正常", "green"
    if pct >= 40:
        return "可增强", "amber"
    return "缺失", "red"


def _tone(pct: int | None) -> str:
    if pct is None:
        return "尚未发现此类页面"
    if pct >= 80:
        return "覆盖较好"
    if pct >= 40:
        return "需要提升"
    return "明显缺口"


def summarize_structure(
    pages: list[dict[str, Any]],
    *,
    brand: str,
    website: str,
    sitemap_url: str | None,
    discovered: int,
) -> dict[str, Any]:
    ok_pages = [p for p in pages if p.get("status") != "错误"]
    failed_pages = [p for p in pages if p.get("status") == "错误"]
    minimum_success = min(3, len(pages))
    enough_sample = bool(ok_pages) and (
        len(pages) <= 2 or (len(ok_pages) >= minimum_success and len(ok_pages) / len(pages) >= 0.5)
    )
    assessment_status = "complete" if enough_sample else "insufficient_sample"
    structured = [p for p in ok_pages if p.get("schema_types")]
    by_type: dict[str, list[dict[str, Any]]] = {}
    for page in ok_pages:
        by_type.setdefault(page["type"], []).append(page)

    def typed(cn: str) -> list[dict[str, Any]]:
        return by_type.get(cn, [])

    def has_type(rows: list[dict[str, Any]], schema: str) -> int:
        return sum(1 for p in rows if schema in (p.get("valid_schema_types") or []))

    product_rows = typed("产品")
    service_rows = typed("服务")
    article_rows = typed("文章")
    faq_rows = typed("FAQ")
    brand_rows = typed("品牌页面")
    org_n = sum(
        1
        for p in brand_rows
        if {"Organization", "Brand", "Corporation"} & set(p.get("valid_schema_types") or [])
    )
    site_n = sum(1 for p in ok_pages if "WebSite" in (p.get("valid_schema_types") or []))
    product_ok = has_type(product_rows, "Product")
    service_ok = has_type(service_rows, "Service")
    article_ok = has_type(article_rows, "Article")
    faq_ok = has_type(faq_rows, "FAQPage")
    crumb_ok = sum(1 for p in ok_pages if "BreadcrumbList" in (p.get("schema_types") or []))
    author_ok = sum(
        1
        for p in article_rows
        if "Person" in (p.get("schema_types") or []) or p.get("has_author")
    )
    org_pct = _pct(org_n, max(1, len(brand_rows) or len(ok_pages)))
    if not brand_rows and not ok_pages:
        org_pct = None
    prod_pct = _pct(product_ok + service_ok, len(product_rows) + len(service_rows))
    faq_pct = _pct(faq_ok, len(faq_rows))
    article_pct = _pct(article_ok, len(article_rows))
    crumb_pct = _pct(crumb_ok, len(ok_pages))
    author_pct = _pct(author_ok, len(article_rows))
    site_pct = 100 if site_n else (0 if ok_pages else None)

    entity_score = org_pct if org_pct is not None else 0
    type_parts = [p for p in (prod_pct, faq_pct, article_pct) if p is not None]
    type_score = round(sum(type_parts) / len(type_parts)) if type_parts else 0
    field_score = author_pct if author_pct is not None else (100 if org_n else 0)
    rel_have = 0
    rel_total = 0
    if product_rows:
        rel_total += 1
        if product_ok:
            rel_have += 1
    rel_total += 1
    if any(p.get("same_as") for p in ok_pages):
        rel_have += 1
    if article_rows:
        rel_total += 1
        if author_ok:
            rel_have += 1
        rel_total += 1
        if any(p.get("about_product") for p in article_rows):
            rel_have += 1
    rel_score = _pct(rel_have, rel_total) or 0
    score = (
        round(entity_score * 0.4 + type_score * 0.3 + field_score * 0.2 + rel_score * 0.1)
        if enough_sample
        else None
    )
    dims = [
        {"label": "核心实体覆盖度 · 40%", "value": entity_score},
        {"label": "页面类型结构覆盖度 · 30%", "value": type_score},
        {"label": "关键字段完整度 · 20%", "value": field_score},
        {"label": "实体关系完整度 · 10%", "value": rel_score},
    ]
    badge = (
        "无法评估"
        if not enough_sample
        else ("结构较好" if score >= 80 else ("需要优化" if score >= 40 else "缺口明显"))
    )

    coverage = [
        {
            "key": "org",
            "label": "品牌 / 企业",
            "schema": "Organization",
            "filter": "品牌页面",
            "value": "已覆盖" if org_n else "未覆盖",
            "status": "正常" if org_n else "缺失",
            "tone": "green" if org_n else "red",
        },
        {
            "key": "website",
            "label": "官网",
            "schema": "WebSite",
            "filter": "品牌页面",
            "value": "已覆盖" if site_n else "未覆盖",
            "status": "正常" if site_n else "缺失",
            "tone": "green" if site_n else "red",
        },
        {
            "key": "product",
            "label": "产品",
            "schema": "Product",
            "filter": "产品",
            "value": f"{product_ok} / {len(product_rows)} 页面" if product_rows else "未发现产品页",
            "status": _badge(prod_pct, empty="未发现")[0],
            "tone": _badge(prod_pct, empty="未发现")[1],
        },
        {
            "key": "service",
            "label": "服务",
            "schema": "Service",
            "filter": "服务",
            "value": f"{service_ok} / {len(service_rows)} 页面" if service_rows else "未发现服务页",
            "status": _badge(_pct(service_ok, len(service_rows)), empty="未发现")[0],
            "tone": _badge(_pct(service_ok, len(service_rows)), empty="未发现")[1],
        },
        {
            "key": "article",
            "label": "文章",
            "schema": "Article",
            "filter": "文章",
            "value": f"{article_ok} / {len(article_rows)} 页面" if article_rows else "未发现文章页",
            "status": _badge(article_pct, empty="未发现")[0],
            "tone": _badge(article_pct, empty="未发现")[1],
        },
        {
            "key": "faq",
            "label": "FAQ",
            "schema": "FAQPage",
            "filter": "FAQ",
            "value": f"{faq_ok} / {len(faq_rows)} 页面" if faq_rows else "未发现 FAQ 页",
            "status": _badge(faq_pct, empty="未发现")[0],
            "tone": _badge(faq_pct, empty="未发现")[1],
        },
        {
            "key": "crumb",
            "label": "导航结构",
            "schema": "BreadcrumbList",
            "filter": "全部",
            "value": f"{crumb_pct}%" if crumb_pct is not None else "—",
            "status": _badge(crumb_pct)[0],
            "tone": _badge(crumb_pct)[1],
        },
        {
            "key": "person",
            "label": "作者",
            "schema": "Person",
            "filter": "文章",
            "value": f"{author_pct}%" if author_pct is not None else "—",
            "status": _badge(author_pct, empty="未发现")[0],
            "tone": _badge(author_pct, empty="未发现")[1],
        },
    ]

    issues: list[dict[str, Any]] = []
    if not enough_sample:
        issues.append(
            {
                "code": "scan_no_successful_pages",
                "pri": "P1",
                "title": "未获得足够的可评估页面",
                "detail": f"本次尝试 {len(pages)} 个 URL，仅成功获取 {len(ok_pages)} 个 HTML 页面，无法给出可靠的官网结构评分。请检查官网可访问性后重新扫描。",
                "paths": [p["url"] for p in failed_pages[:3]],
                "extra": max(0, len(failed_pages) - 3),
                "filter": "全部",
            }
        )
    missing_product = [p for p in product_rows if "Product" not in (p.get("valid_schema_types") or [])]
    if missing_product:
        issues.append(
            {
                "pri": "P1",
                "title": f"{len(missing_product)} 个产品页面缺少 Product Schema",
                "detail": "页面已能打开，但没有通过 Product 明确产品名称与品牌归属。",
                "paths": [p["url"] for p in missing_product[:3]],
                "extra": max(0, len(missing_product) - 3),
                "filter": "产品",
            }
        )
    missing_faq = [p for p in faq_rows if "FAQPage" not in (p.get("valid_schema_types") or [])]
    if missing_faq:
        issues.append(
            {
                "pri": "P1",
                "title": f"{len(missing_faq)} 个 FAQ 页面缺少 FAQPage",
                "detail": "页面已有问答痕迹，但没有 Question → Answer 结构化关系。",
                "paths": [p["url"] for p in missing_faq[:3]],
                "extra": max(0, len(missing_faq) - 3),
                "filter": "FAQ",
            }
        )
    weak_org = [p for p in brand_rows if p.get("status") == "可增强"]
    if weak_org or (ok_pages and not org_n):
        issues.append(
            {
                "pri": "P2",
                "title": "Organization 信息可增强" if org_n else "缺少 Organization",
                "detail": "建议补齐品牌主体、官网 URL，以及能核验的官方账号（sameAs）。",
                "paths": [p["url"] for p in (weak_org or brand_rows or ok_pages)[:3]],
                "extra": 0,
                "filter": "品牌页面",
                "open_id": (weak_org or brand_rows or ok_pages)[0]["id"] if (weak_org or brand_rows or ok_pages) else "",
            }
        )

    same_as_all: list[str] = []
    for page in ok_pages:
        for item in page.get("same_as") or []:
            if item not in same_as_all:
                same_as_all.append(item)
    product_names = [p.get("title") or p.get("name") for p in product_rows if p.get("title") or p.get("name")]
    home_url = website
    product_json = suggest_jsonld(
        page_type="产品",
        url=product_rows[0]["full_url"] if product_rows else website,
        title=product_names[0] if product_names else brand,
        brand=brand,
        summary="",
        questions=[],
        same_as=[],
    )
    org_json = suggest_jsonld(
        page_type="品牌页面",
        url=home_url,
        title=brand,
        brand=brand,
        summary="",
        questions=[],
        same_as=same_as_all,
    )
    author_json = suggest_jsonld(
        page_type="文章",
        url=article_rows[0]["full_url"] if article_rows else website,
        title=(article_rows[0].get("title") if article_rows else "") or brand,
        brand=brand,
        summary="",
        questions=[],
        same_as=[],
    )
    about_json = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": (article_rows[0].get("title") if article_rows else brand) or "文章",
        "url": article_rows[0]["full_url"] if article_rows else website,
        "about": {"@type": "Product", "name": product_names[0] if product_names else "产品"},
    }
    rel_cards = [
        {
            "id": "product",
            "title": "品牌与产品",
            "status": "已建立" if product_ok else ("缺失" if product_rows else "未发现产品页"),
            "tone": "green" if product_ok else ("red" if product_rows else "amber"),
            "expr_left": brand or website,
            "expr_right": product_names[0] if product_names else "产品页",
            "detail": (
                f"已扫描到 {product_ok} 个带 Product 的产品页。"
                if product_ok
                else ("扫描到产品页，但还没有 Product Schema。" if product_rows else "sitemap 抽样里还没有识别到产品页。")
            ),
            "tech": "Organization / Brand / Product",
            "cta": "查看详情",
            "sub": "检查品牌主体与产品之间是否已经建立明确归属",
            "jsonld": product_json,
            "fields": [
                {"key": "name", "value": product_names[0] if product_names else "—", "source": "产品页标题"},
                {"key": "brand", "value": brand or "—", "source": "品牌信息"},
            ],
        },
        {
            "id": "channels",
            "title": "品牌与官方渠道",
            "status": "已建立" if same_as_all else "缺失",
            "tone": "green" if same_as_all else "red",
            "expr_left": brand or website,
            "expr_right": " · ".join(same_as_all[:4]) if same_as_all else "未发现 sameAs",
            "detail": (
                f"Organization 已声明 {len(same_as_all)} 个官方账号。"
                if same_as_all
                else "当前扫描未读到 Organization.sameAs。品牌信息里也没有独立的官方账号字段。"
            ),
            "tech": "Organization.sameAs",
            "cta": "查看缺失渠道",
            "sub": "检查品牌主体与外部官方账号之间的关联",
            "jsonld": org_json,
            "fields": [
                {"key": "name", "value": brand or "—", "source": "品牌信息"},
                {"key": "sameAs", "value": "、".join(same_as_all) or "未发现", "source": "页面 Organization JSON-LD"},
            ],
        },
        {
            "id": "author",
            "title": "文章与作者",
            "status": f"覆盖 {author_pct}%" if author_pct is not None else "未发现文章页",
            "tone": _badge(author_pct, empty="未发现")[1],
            "expr_left": f"{len(article_rows)} 篇文章" if article_rows else "文章页",
            "expr_right": f"{author_ok} 篇已明确作者" if article_rows else "—",
            "detail": (
                f"抽样 {len(article_rows)} 篇，其中 {author_ok} 篇能识别作者或 Person。"
                if article_rows
                else "sitemap 抽样里还没有识别到文章页。"
            ),
            "tech": "Article.author → Person",
            "cta": "查看未覆盖文章",
            "sub": f"{len(article_rows)} 篇文章中 {author_ok} 篇已明确作者" if article_rows else "未发现文章页",
            "jsonld": author_json,
            "fields": [
                {"key": "headline", "value": (article_rows[0].get("title") if article_rows else "—") or "—", "source": "页面 H1"},
                {"key": "author", "value": "页面作者署名 / Person", "source": "扫描识别"},
            ],
            "uncovered": [p["url"] for p in article_rows if not p.get("has_author") and "Person" not in (p.get("schema_types") or [])][:6],
        },
        {
            "id": "about",
            "title": "文章与产品",
            "status": "已建立" if any(p.get("about_product") for p in article_rows) else ("缺失" if article_rows else "未发现文章页"),
            "tone": "green" if any(p.get("about_product") for p in article_rows) else ("red" if article_rows else "amber"),
            "expr_left": "文章",
            "expr_right": product_names[0] if product_names else "产品",
            "detail": (
                "已有文章通过 about / mentions 指向 Product。"
                if any(p.get("about_product") for p in article_rows)
                else "扫描未发现 Article.about / mentions 指向产品实体。"
            ),
            "tech": "Article.about / mentions",
            "cta": "查看建议",
            "sub": "检查文章是否明确表达主要介绍哪个产品",
            "jsonld": about_json,
            "fields": [
                {"key": "headline", "value": (article_rows[0].get("title") if article_rows else "—") or "—", "source": "页面 H1"},
                {"key": "about", "value": product_names[0] if product_names else "—", "source": "正文主题 / 产品页"},
            ],
        },
    ]
    gaps = []
    if not product_ok and product_rows:
        gaps.append("产品")
    if not faq_ok and faq_rows:
        gaps.append("FAQ")
    if not service_ok and service_rows:
        gaps.append("服务")
    insight = (
        f"本次尝试 {len(pages)} 个页面，成功解析 {len(ok_pages)} 页、抓取失败 {len(failed_pages)} 页，样本不足，无法完成可靠的结构评估。"
        if not enough_sample
        else (
            f"已扫描 {len(pages)} 个页面，其中 {len(structured)} 个带有 JSON-LD。"
            + (f" 优先补齐{'、'.join(gaps)} 的结构化表达。" if gaps else " 机器可解析的基础结构已经能读到。")
        )
    )

    return {
        "kind": "website_structure",
        "website": website,
        "sitemap_url": sitemap_url,
        "discovered": discovered,
        "page_count": len(pages),
        "successful_page_count": len(ok_pages),
        "failed_page_count": len(failed_pages),
        "assessment_status": assessment_status,
        "minimum_successful_page_count": minimum_success,
        "structured_count": len(structured),
        "score": score,
        "score_dims": dims,
        "score_badge": badge,
        "insight": insight,
        "coverage": coverage,
        "callouts": [
            {
                "filter": "品牌页面",
                "tone": _tone(org_pct if org_n else 0),
                "name": "品牌 / 组织",
                "pct": org_pct if org_n else 0,
            },
            {
                "filter": "产品",
                "tone": _tone(prod_pct),
                "name": "产品 / 服务",
                "pct": prod_pct,
            },
            {
                "filter": "FAQ",
                "tone": _tone(faq_pct),
                "name": "FAQ",
                "pct": faq_pct,
            },
        ],
        "issues": issues[:5],
        "pages": pages,
        "relations": {
            "completeness": rel_score,
            "badge": "需要增强" if rel_score < 80 else "已建立",
            "summary": insight,
            "cards": rel_cards,
        },
        "type_counts": dict(Counter(p["type"] for p in ok_pages)),
    }


async def inspect_page(url: str, *, brand: str, summary: str) -> dict[str, Any]:
    from app.geo.audit import GeoAuditError

    try:
        document = await safe_fetch(url)
    except GeoAuditError as exc:
        return build_page_row(
            url=url,
            title="",
            types=[],
            h1s=[],
            has_author=False,
            has_date=False,
            questions=[],
            same_as=[],
            about_product=False,
            items=[],
            brand=brand,
            summary=summary,
            error=str(exc)[:120],
        )
    raw = BeautifulSoup(document.html, "html.parser")
    items = _json_ld_items(raw)
    types = sorted(_schema_types(items))
    same_as = _collect_same_as(items)
    about_product = _has_about_product(items)
    soup = BeautifulSoup(document.html, "html.parser")
    for node in soup(["script", "style", "noscript", "template", "svg"]):
        node.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    h1s = [n.get_text(" ", strip=True) for n in soup.find_all("h1") if n.get_text(" ", strip=True)][:3]
    headings = [n.get_text(" ", strip=True) for n in soup.find_all(re.compile(r"^h[1-6]$")) if n.get_text(" ", strip=True)]
    questions = [
        h
        for h in headings
        if re.search(r"[?？]$|^(什么|如何|为什么|是否|怎么|哪)|^(When|What|How|Why)\b", h, re.I)
    ][:12]
    has_author = bool(soup.select_one('[rel="author"], [itemprop="author"], meta[name="author" i]'))
    has_date = bool(
        soup.select_one("time[datetime], [itemprop='datePublished'], meta[property='article:published_time']")
    )
    return build_page_row(
        url=document.final_url or url,
        title=title,
        types=types,
        h1s=h1s,
        has_author=has_author,
        has_date=has_date,
        questions=questions,
        same_as=same_as,
        about_product=about_product,
        items=items,
        brand=brand,
        summary=summary,
    )


def pick_scan_urls(site_url: str, urls: list[str], *, limit: int = MAX_PAGES) -> list[str]:
    """Skip API/machine paths and round-robin page kinds so sitemap order cannot fill the cap."""
    parsed = urlparse(site_url)
    home = f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else site_url
    filtered: list[str] = []
    seen: set[str] = set()
    for url in (home, site_url, *urls):
        key = _scan_url_key(url)
        if not url or key in seen or skip_reason(url):
            continue
        seen.add(key)
        filtered.append(url)
    buckets: dict[str, list[str]] = {kind: [] for kind in _PICK_KIND_ORDER}
    for url in filtered:
        kind = page_kind(url)
        buckets[kind if kind in buckets else "other"].append(url)
    picked: list[str] = []
    while len(picked) < limit:
        moved = False
        for kind in _PICK_KIND_ORDER:
            bucket = buckets.get(kind) or []
            if not bucket:
                continue
            picked.append(bucket.pop(0))
            moved = True
            if len(picked) >= limit:
                break
        if not moved:
            break
    return picked or [site_url]


async def scan_website(site_url: str, *, brand: str = "", summary: str = "") -> dict[str, Any]:
    sitemap_url, urls = await discover_sitemap_urls(site_url)
    picked = pick_scan_urls(site_url, urls, limit=MAX_PAGES)
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def one(url: str) -> dict[str, Any]:
        async with sem:
            return await inspect_page(url, brand=brand, summary=summary)

    pages = list(await asyncio.gather(*[one(u) for u in picked]))
    return summarize_structure(
        pages,
        brand=brand,
        website=site_url,
        sitemap_url=sitemap_url,
        discovered=len(urls),
    )
