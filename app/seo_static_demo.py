"""Read-only, versioned SEO fixture adapter for the approved demo identity.

The adapter is deliberately in-process: it needs no fixture database and never
calls a crawler, provider, generator, scheduler, publisher, or ORM business
handler.  Authentication still comes from the primary account store.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials

from app.database import async_session_factory
from app.security.auth import AuthContext, require_auth


DEMO_TENANT_ID = 16
DEMO_SITE_ID = 1601
DEMO_USERNAME = "workbench_test_readonly"
DEMO_DATASET_VERSION = "2026.09.10-v1"
FIXTURE_PATH = Path(__file__).with_name("fixtures") / "seo_demo_tenant16_v1.json"
_DETAIL_RE = re.compile(r"^/api/v1/seo/(keywords|site-pages)/(\d+)(?:/detail)?$")
_REVIEW_HISTORY_RE = re.compile(r"^/api/v1/seo/content-assets/(\d+)/review-history$")
_ATTEMPTS_RE = re.compile(
    r"^/api/v1/seo/content-distribution/publications/(\d+)/attempts$"
)
_SIMULATED_ACTIONS = (
    re.compile(r"^/api/v1/seo/content-assets/\d+/(?:submit-review|review)$"),
    re.compile(r"^/api/v1/seo/site-pages/\d+/audit$"),
    re.compile(
        r"^/api/v1/seo/content-distribution/publications/\d+/(?:sync|retry)$"
    ),
    re.compile(r"^/api/v1/seo/overview/(?:collect-metrics|automation-runs/trigger)$"),
)


@dataclass(frozen=True)
class DemoResponse:
    status_code: int
    payload: dict[str, Any] | list[Any]


def load_fixture() -> dict[str, Any]:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    dataset = fixture.get("dataset") or {}
    if (
        dataset.get("tenant_id") != DEMO_TENANT_ID
        or dataset.get("site_id") != DEMO_SITE_ID
        or dataset.get("version") != DEMO_DATASET_VERSION
    ):
        raise RuntimeError("SEO static demo fixture identity/version mismatch")
    return fixture


def _int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return result if str(value).strip() == str(result) else None


def _page(items: list[dict[str, Any]], query: Mapping[str, str]) -> dict[str, Any]:
    page = max(_int(query.get("page")) or 1, 1)
    page_size = min(max(_int(query.get("page_size")) or 50, 1), 200)
    start = (page - 1) * page_size
    return {
        "items": items[start : start + page_size],
        "total": len(items),
        "page": page,
        "page_size": page_size,
    }


def _select(items: list[dict[str, Any]], query: Mapping[str, str]) -> list[dict[str, Any]]:
    selected = items
    for field in ("site_id", "content_id", "page_id", "source_page_id"):
        value = query.get(field)
        if value not in (None, "") and any(field in row for row in selected):
            expected: Any = _int(value)
            selected = [row for row in selected if row.get(field) == expected]
    status = str(query.get("status") or "").strip()
    if status and any("status" in row for row in selected):
        statuses = {value.strip() for value in status.split(",") if value.strip()}
        selected = [row for row in selected if row.get("status") in statuses]
    raw_types = str(query.get("content_types") or query.get("content_type") or "").strip()
    if raw_types and any("content_type" in row for row in selected):
        content_types = {value.strip() for value in raw_types.split(",") if value.strip()}
        selected = [row for row in selected if row.get("content_type") in content_types]
    term = str(query.get("q") or "").strip().casefold()
    if term:
        selected = [
            row
            for row in selected
            if term in " ".join(str(row.get(k) or "") for k in ("title", "url", "keyword", "cluster")).casefold()
        ]
    return selected


def _dataset_meta(fixture: dict[str, Any]) -> dict[str, Any]:
    dataset = fixture["dataset"]
    return {
        "demo": True,
        "persisted": False,
        "dataset_key": dataset["key"],
        "dataset_version": dataset["version"],
        "as_of": dataset["as_of"],
        "source_notice": dataset["source_notice"],
    }


def _site_page_list(fixture: dict[str, Any], query: Mapping[str, str]) -> dict[str, Any]:
    rows = _select(deepcopy(fixture["pages"]), query)
    for row in rows:
        row.setdefault("page_type", None)
        row.setdefault("target_keyword_id", None)
        row.setdefault("meta_keywords", None)
        row.setdefault("h1", None)
        row.setdefault("canonical", row.get("canonical_url"))
        row.setdefault("content_units", None)
        row.setdefault("title_suggestion", None)
        row.setdefault("description_suggestion", None)
        row.setdefault("content_task_id", None)
        row.setdefault("created_at", row.get("last_checked_at"))
        checked_at = row.get("last_checked_at")
        assessment_state = (
            "unavailable"
            if not checked_at or row.get("last_error") or row.get("http_status") is None
            else "assessed"
        )
        row["diagnostic"] = {
            "assessment_state": assessment_state,
            "audit_score": row.get("audit_score") if assessment_state == "assessed" else None,
            "detection_source": "program",
            "guidance_source": "rules",
            "index_intent_source": "human",
            "ai_used": False,
            "http_status": None if row.get("last_error") else row.get("http_status"),
            "checked_at": checked_at,
            "index_control": (
                "no_restriction_detected" if row.get("indexable") is True else "unknown"
            ),
            "search_engine_indexed": None,
            "index_intent": "undecided",
            "review_outcome": "needs_review",
            "guidance": "这是演示数据；请结合最近一次存档检测人工确认页面索引意图。",
            "index_evidence_codes": [],
            "ai_crawler_codes": [],
            "note": "基于静态演示的最近一次存档检测，不是实时监控；允许索引不等于已收录。",
        }
    result = _page(rows, query)
    all_rows = fixture["pages"]
    result["stats"] = {
        "total": len(all_rows),
        "healthy": sum(row["status"] == "healthy" for row in all_rows),
        "needs_fix": sum(row["status"] == "needs_fix" for row in all_rows),
        "unchecked": 0,
        "proposed": 0,
        "approved": 0,
        "implemented": 0,
        "verified": 0,
        "average_score": round(sum(row["audit_score"] for row in all_rows) / len(all_rows), 1),
    }
    result["demo_meta"] = _dataset_meta(fixture)
    return result


def _overview(fixture: dict[str, Any]) -> dict[str, Any]:
    pages = fixture["pages"]
    keywords = fixture["keywords"]
    contents = fixture["contents"]
    publications = fixture["publications"]
    ranked = [row for row in keywords if row.get("latest_rank") is not None]
    top10 = sum(row["latest_rank"] <= 10 for row in ranked)
    top20 = sum(row["latest_rank"] <= 20 for row in ranked)
    unavailable_metric = {"status": "not_configured", "value": None, "unit": None, "source": None, "message": "静态演示未连接外部指标平台"}
    site = fixture["site"]
    return {
        "engine": "baidu",
        "site": {"id": site["id"], "name": site["name"], "domain": site["canonical_domain"], "default_url": site["domain"]},
        "last_updated_at": fixture["dataset"]["as_of"],
        "stats": {
            "keywords": len(keywords), "ranked": len(ranked), "top10": top10,
            "top20": top20, "top50": sum(row["latest_rank"] <= 50 for row in ranked),
            "average_position": round(sum(row["latest_rank"] for row in ranked) / len(ranked), 1),
            "rises": sum((row.get("previous_rank") or 999) > row["latest_rank"] for row in ranked),
            "falls": sum(row.get("previous_rank") is not None and row["previous_rank"] < row["latest_rank"] for row in ranked),
            "top10_rate": round(top10 / max(len(ranked), 1) * 100, 1), "rank_anomalies": 1,
            "new_keywords_30d": len(keywords), "pages": len(pages),
            "healthy_pages": sum(row["status"] == "healthy" for row in pages),
            "pages_needing_fix": sum(row["status"] == "needs_fix" for row in pages),
            "content_active": sum(row["status"] in {"planned", "drafting", "review", "ready"} for row in contents),
            "content_published": sum(row["status"] == "published" for row in contents),
            "backlinks": 0, "competitors": 0, "crawl_fetched": len(pages),
            "crawl_failed": 0, "crawl_blocked": 0,
            "crawl_issues": sum(bool(row["issue_codes"]) for row in pages),
        },
        "metrics": {
            "indexing": deepcopy(unavailable_metric),
            "keyword_coverage": {"desktop": deepcopy(unavailable_metric), "mobile": deepcopy(unavailable_metric)},
            "estimated_traffic": {"desktop": deepcopy(unavailable_metric), "mobile": deepcopy(unavailable_metric)},
            "baidu_weight": {"desktop": deepcopy(unavailable_metric), "mobile": deepcopy(unavailable_metric)},
            "verified_traffic": {**deepcopy(unavailable_metric), "message": fixture["search_clicks"]["message"]},
        },
        "crawl": {"id": 1605001, "status": "completed", "fetched_count": len(pages), "failed_count": 0, "blocked_count": 0, "issue_count": sum(bool(row["issue_codes"]) for row in pages), "started_at": fixture["dataset"]["as_of"], "completed_at": fixture["dataset"]["as_of"], "synthetic": False, "source": "public_preflight"},
        "opportunities": deepcopy(keywords),
        "page_issues": deepcopy(pages[:8]),
        "collection_status": [{"engine": engine, "collected": len(keywords) if engine == "baidu" else 0, "total": len(keywords), "status": "ready" if engine == "baidu" else "unavailable"} for engine in ("baidu", "google", "bing", "360", "sogou")],
        "trend": [
            {"date": "2026-08-27", "top10": 0, "top20": 1},
            {"date": "2026-09-03", "top10": 0, "top20": 2},
            {"date": "2026-09-10", "top10": top10, "top20": top20},
        ],
        "tasks": [
            {"type": "site", "count": sum(row["status"] == "needs_fix" for row in pages), "title": "页面问题待优化", "detail": "公开页面预采集发现 H1、图片 Alt 和语言声明问题", "action": "查看页面", "path": "/seo/site"},
            {"type": "content", "count": sum(row["status"] in {"drafting", "review", "ready"} for row in contents), "title": "内容任务等待推进", "detail": "演示审核、待发布和退回状态", "action": "进入内容", "path": "/seo/content/articles"},
        ],
        "search_clicks": deepcopy(fixture["search_clicks"]),
        "demo_meta": _dataset_meta(fixture),
    }


def _keyword_list(fixture: dict[str, Any], query: Mapping[str, str]) -> dict[str, Any]:
    rows = _select(deepcopy(fixture["keywords"]), query)
    for row in rows:
        row["monitored_engines"] = [row["engine"]]
    result = _page(rows, query)
    result["engine"] = query.get("engine") or "baidu"
    result["stats"] = {
        "total": len(fixture["keywords"]),
        "active": len(fixture["keywords"]),
        "monthly_volume": sum(row.get("monthly_volume") or 0 for row in fixture["keywords"]),
        "with_landing_page": sum(bool(row.get("landing_page")) for row in fixture["keywords"]),
        "high_priority": sum(row.get("priority") in {"P0", "P1"} for row in fixture["keywords"]),
        "commercial_intent": sum(row.get("intent") in {"商业", "产品", "价格", "方案", "对比", "决策"} for row in fixture["keywords"]),
        "monitored_engines": ["baidu"],
    }
    result["demo_meta"] = _dataset_meta(fixture)
    return result


def _demo_provider(fixture: dict[str, Any]) -> dict[str, Any]:
    return {
        "configured": False,
        "status": "not_connected",
        "message": "静态演示未连接付费外链索引；页面不会产生供应商调用。",
        "demo_meta": _dataset_meta(fixture),
    }


def _backlink_analysis(fixture: dict[str, Any]) -> dict[str, Any]:
    rows = fixture["backlinks"]
    found = [row for row in rows if row.get("verification", {}).get("state") == "found"]
    def counts(field: str) -> list[dict[str, Any]]:
        values: dict[str, int] = {}
        for row in found:
            value = str(row.get(field) or "未提供")
            values[value] = values.get(value, 0) + 1
        return [{"name": name, "count": count} for name, count in sorted(values.items(), key=lambda item: (-item[1], item[0]))]
    domains = counts("source_domain")
    top = domains[0]["count"] if domains else 0
    attributes: dict[str, int] = {}
    for row in found:
        labels = row.get("verification", {}).get("rel") or ["follow"]
        for label in labels:
            attributes[label] = attributes.get(label, 0) + 1
    return {
        "pending": sum(row.get("verification", {}).get("state") == "pending" for row in rows),
        "unavailable": sum(row.get("verification", {}).get("state") in {"blocked", "unreachable"} for row in rows),
        "referring_domains": len(domains),
        "top_domain_share": round(top / max(len(found), 1) * 100, 1),
        "domains": domains,
        "anchors": counts("anchor_text"),
        "targets": counts("target_url"),
        "attributes": [{"name": name, "count": count} for name, count in sorted(attributes.items())],
        "trend": deepcopy(fixture["backlink_trend"]),
        "demo_meta": _dataset_meta(fixture),
    }


def resolve_demo_response(
    method: str,
    path: str,
    query: Mapping[str, str],
    body: Mapping[str, Any] | None = None,
) -> DemoResponse:
    """Resolve every supported tenant-16 request without business side effects."""
    fixture = load_fixture()
    method = method.upper()
    path = path.rstrip("/") or "/"
    if method == "GET" and path == "/api/v1/seo/sites":
        return DemoResponse(200, {"sites": [deepcopy(fixture["site"])], "demo_meta": _dataset_meta(fixture)})
    if method == "GET" and path == "/api/v1/seo/workbench/sites":
        site = fixture["site"]
        return DemoResponse(200, {"tenant_id": DEMO_TENANT_ID, "selection_policy": {"selectable_statuses": ["active"], "disabled_statuses": ["paused", "archived"]}, "sites": [{"id": site["id"], "name": site["name"], "domain": site["domain"], "status": site["status"]}], "demo_meta": _dataset_meta(fixture)})
    if method == "GET" and path == "/api/v1/seo/overview":
        return DemoResponse(200, _overview(fixture))
    if method == "GET" and path == "/api/v1/seo/overview/task-center":
        rows = _select(deepcopy(fixture["task_runs"]), query)
        kind = str(query.get("kind") or "").strip()
        if kind:
            rows = [row for row in rows if row.get("kind") == kind]
        result = _page(rows, query)
        result["summary"] = {
            status: sum(row["status"] == status for row in fixture["task_runs"])
            for status in {row["status"] for row in fixture["task_runs"]}
        }
        result["schedules"] = deepcopy(fixture["task_schedules"])
        result["demo_meta"] = _dataset_meta(fixture)
        return DemoResponse(200, result)
    if method == "GET" and path == "/api/v1/seo/overview/customer-verification-queue":
        first_page = fixture["pages"][0]
        first_publication = fixture["publications"][0]
        first_backlink = fixture["backlinks"][0]
        rows = [
            {"id": f"page_recheck:{first_page['id']}", "kind": "page_recheck", "state": "pending_customer_action",
             "title": f"页面重新检查 · {first_page['title']}", "detail": "优化建议尚待客户在网站实施",
             "source_id": first_page["id"], "site_id": DEMO_SITE_ID, "updated_at": first_page["updated_at"],
             "evidence": {"url": first_page["url"], "http_status": first_page["http_status"], "audit_score": first_page["audit_score"], "issue_codes": first_page["issue_codes"], "last_checked_at": first_page["last_checked_at"]},
             "action_url": f"/seo/site?site_id={DEMO_SITE_ID}"},
            {"id": f"publication_url:{first_publication['id']}", "kind": "publication_url", "state": "pending_system_check",
             "title": f"{first_publication['platform_name']}发布地址 · {first_publication['content_title']}", "detail": "已回填公开地址，等待系统抓取核验",
             "source_id": first_publication["id"], "site_id": DEMO_SITE_ID, "updated_at": first_publication["updated_at"],
             "evidence": {"page_url": first_publication["page_url"], "published_at": first_publication["published_at"], "link_discovery": None},
             "action_url": f"/seo/distribution?site_id={DEMO_SITE_ID}"},
            {"id": f"backlink_verification:{first_backlink['id']}", "kind": "backlink_verification", "state": "verified",
             "title": f"外链核验 · {first_backlink['source_domain']}", "detail": "抓取已确认来源页存在目标链接",
             "source_id": first_backlink["id"], "site_id": DEMO_SITE_ID, "updated_at": first_backlink["last_checked_at"],
             "evidence": {"source_url": first_backlink["source_url"], "target_url": first_backlink["target_url"], "verification": first_backlink["verification"], "last_checked_at": first_backlink["last_checked_at"]},
             "action_url": f"/seo/links?site_id={DEMO_SITE_ID}&tab=backlink"},
        ]
        state = str(query.get("state") or "").strip()
        kind = str(query.get("kind") or "").strip()
        if state: rows = [row for row in rows if row["state"] == state]
        if kind: rows = [row for row in rows if row["kind"] == kind]
        result = _page(rows, query)
        result.update({"summary": {value: sum(row["state"] == value for row in rows) for value in ("pending_customer_action", "pending_system_check", "verified", "failed_retry")},
                       "state_definitions": {"pending_customer_action": "需要客户或运营人员先完成真实网站/平台操作", "pending_system_check": "等待系统抓取或平台核验", "verified": "系统已取得真实页面或平台证据", "failed_retry": "核验失败或证据不可用，可以重试"},
                       "read_only": True, "as_of": fixture["dataset"]["as_of"], "scanned_count": len(rows),
                       "source_counts": {}, "truncated": False, "truncated_sources": [], "has_more": False,
                       "demo_meta": _dataset_meta(fixture)})
        return DemoResponse(200, result)
    if method == "GET" and path == "/api/v1/seo/alerts":
        rows = deepcopy(fixture["alerts"])
        return DemoResponse(200, {
            "items": rows,
            "total": len(rows),
            "high": sum(row["severity"] == "high" for row in rows),
            "demo_meta": _dataset_meta(fixture),
        })
    if method == "GET" and path == "/api/v1/seo/rank-serp/brand-profile":
        return DemoResponse(200, deepcopy(fixture["brand_profile"]) | {"demo_meta": _dataset_meta(fixture)})
    if method == "GET" and path == "/api/v1/seo/content-assets":
        rows = _select(deepcopy(fixture["contents"]), query)
        result = _page(rows, query)
        result["status_counts"] = {status: sum(row["status"] == status for row in fixture["contents"]) for status in {row["status"] for row in fixture["contents"]}}
        result["demo_meta"] = _dataset_meta(fixture)
        return DemoResponse(200, result)
    match = _REVIEW_HISTORY_RE.fullmatch(path)
    if method == "GET" and match:
        content_id = match.group(1)
        rows = deepcopy(fixture["review_history"].get(content_id, []))
        if not any(row["id"] == int(content_id) for row in fixture["contents"]):
            return DemoResponse(404, {"detail": "演示内容不存在", "code": "demo_not_found"})
        return DemoResponse(200, {"items": rows, "total": len(rows), "demo_meta": _dataset_meta(fixture)})
    if method == "GET" and path == "/api/v1/seo/content-distribution/publications":
        rows = _select(deepcopy(fixture["publications"]), query)
        return DemoResponse(200, {"items": rows, "total": len(rows), "status_counts": {s: sum(row["status"] == s for row in rows) for s in {row["status"] for row in rows}}, "demo_meta": _dataset_meta(fixture)})
    if method == "GET" and path in {
        "/api/v1/seo/content-distribution/connections",
        "/api/v1/seo/content-distribution/variants",
    }:
        return DemoResponse(200, {"items": [], "total": 0, "status_counts": {}, "demo_meta": _dataset_meta(fixture)})
    if method == "GET" and path == "/api/v1/seo/rank-serp/brand-assets":
        rows = deepcopy(fixture["brand_assets"])
        return DemoResponse(200, {"items": rows, "total": len(rows), "demo_meta": _dataset_meta(fixture)})
    match = _ATTEMPTS_RE.fullmatch(path)
    if method == "GET" and match:
        publication_id = match.group(1)
        rows = deepcopy(fixture["publication_attempts"].get(publication_id, []))
        if not any(row["id"] == int(publication_id) for row in fixture["publications"]):
            return DemoResponse(404, {"detail": "演示发布记录不存在", "code": "demo_not_found"})
        return DemoResponse(200, {"items": rows, "total": len(rows), "demo_meta": _dataset_meta(fixture)})
    if method == "GET" and path == "/api/v1/seo/site-pages":
        return DemoResponse(200, _site_page_list(fixture, query))
    if method == "GET" and path == "/api/v1/seo/site-pages/issues":
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in fixture["pages"]:
            for code in row["issue_codes"]:
                groups.setdefault(code, []).append(row)
        items = [{"key": code, "label": code, "severity": "high" if code == "image_alt_missing" else "medium", "affected_pages": len(rows), "codes": [{"code": code, "count": len(rows)}], "pages": [{"id": row["id"], "url": row["url"], "title": row["title"], "status": row["status"], "audit_score": row["audit_score"], "last_checked_at": row["last_checked_at"]} for row in rows[:100]]} for code, rows in groups.items()]
        return DemoResponse(200, {"items": items, "summary": {"groups": len(items), "high": sum(row["severity"] == "high" for row in items), "medium": sum(row["severity"] == "medium" for row in items), "low": 0, "affected_pages": len(fixture["pages"])}, "demo_meta": _dataset_meta(fixture)})
    match = _DETAIL_RE.fullmatch(path)
    if method == "GET" and match:
        kind, raw_id = match.groups()
        key = "keywords" if kind == "keywords" else "pages"
        row = next((deepcopy(item) for item in fixture[key] if item["id"] == int(raw_id)), None)
        if row is None:
            return DemoResponse(404, {"detail": "演示记录不存在", "code": "demo_not_found"})
        if kind == "keywords":
            history = [deepcopy(item) for item in fixture["rankings"] if item["keyword_id"] == row["id"]]
            payload = {"keyword": row, "rank_history": history, "competitor_history": {}, "engine": query.get("engine") or "baidu", "region": query.get("region") or "全国", "optimization_task": None, "diagnoses": [{"type": "internal_links", "title": "核对相关内链与主题覆盖", "detail": "演示建议：检查承接页标题、H1、正文和自然内链。", "priority": "P2", "content_task_id": None}], "demo_meta": _dataset_meta(fixture)}
            return DemoResponse(200, payload)
        else:
            page = _site_page_list({**fixture, "pages": [row]}, {})["items"][0]
            issue_details = [{"code": code, "group": "image" if code == "image_alt_missing" else "other", "label": code, "severity": "low", "guidance": "结合公开页面检查证据人工核对并修复。"} for code in row["issue_codes"]]
            snapshot = {"id": row["id"] + 100000, "site_id": row["site_id"], "url": row["url"], "final_url": row["url"], "status_code": row["http_status"], "canonical_url": row["canonical_url"], "indexable": row["indexable"], "title": row["title"], "title_length": len(row["title"] or ""), "meta_description": row["meta_description"], "description_length": len(row["meta_description"] or ""), "h1_texts": [], "word_count": None, "schema_types": [], "images_missing_alt_count": row["images_missing_alt_count"], "response_time_ms": row["response_time_ms"], "redirect_chain": [], "fetched_at": row["last_checked_at"], "fetch_error": row["last_error"], "source": row["evidence_source"]}
            payload = {"page": page, "issue_details": issue_details, "internal_links": {"incoming": 0, "outgoing": row["internal_links_count"], "incoming_sources": [], "incoming_sources_truncated": False}, "latest_snapshot": snapshot, "previous_snapshot": None, "comparison": {"available": False, "changed_fields": [], "resolved_issues": [], "new_issues": []}, "read_only": True, "demo_meta": _dataset_meta(fixture)}
            return DemoResponse(200, payload)
    if method == "GET" and path == "/api/v1/seo/keywords":
        return DemoResponse(200, _keyword_list(fixture, query))
    if method == "GET" and path == "/api/v1/seo/rank-serp/results":
        rows = deepcopy(fixture["rankings"])
        keyword_id = _int(query.get("keyword_id"))
        if keyword_id:
            rows = [row for row in rows if row["keyword_id"] == keyword_id]
        return DemoResponse(200, {"items": rows, "total": len(rows), "demo_meta": _dataset_meta(fixture)})
    if method == "GET" and path == "/api/v1/seo/automation-runs":
        return DemoResponse(200, {"items": [], "latest_by_job": {}, "demo_meta": _dataset_meta(fixture)})
    if method == "GET" and path == "/api/v1/seo/site/crawl-runs":
        return DemoResponse(200, {"runs": [], "snapshots": [], "demo_meta": _dataset_meta(fixture)})
    if method == "GET" and path == "/api/v1/seo/rank-serp/collect-status":
        return DemoResponse(200, {"allowed": False, "reason": "static_demo_read_only", "retry_after_seconds": None, "demo_meta": _dataset_meta(fixture)})
    if method == "GET" and path == "/api/v1/seo/rank-serp/providers":
        unavailable = {"configured": False, "status": "not_connected", "reason": "静态演示数据未连接排名供应商"}
        return DemoResponse(200, {engine: deepcopy(unavailable) for engine in ("baidu", "google", "bing", "360", "sogou")} | {"demo_meta": _dataset_meta(fixture)})
    if method == "GET" and path == "/api/v1/seo/traffic/gsc":
        return DemoResponse(200, {**deepcopy(fixture["search_clicks"]), "tenant_id": DEMO_TENANT_ID, "site_id": DEMO_SITE_ID, "demo_meta": _dataset_meta(fixture)})
    if method == "GET" and path == "/api/v1/seo/site-pages/image-evidence":
        page_id = _int(query.get("page_id"))
        row = next((item for item in fixture["pages"] if item["id"] == page_id), None)
        if row is None:
            return DemoResponse(404, {"detail": "演示页面不存在", "code": "demo_not_found"})
        snapshot_id = row["id"] + 100000
        requested_snapshot_id = _int(query.get("snapshot_id"))
        if requested_snapshot_id is not None and requested_snapshot_id != snapshot_id:
            return DemoResponse(404, {"detail": "演示页面快照不存在", "code": "demo_not_found"})
        return DemoResponse(200, {"page_id": page_id, "url": row["url"], "snapshot_id": snapshot_id, "fetched_at": row["last_checked_at"], "fetch_error": row["last_error"], "evidence": None, "source": row["evidence_source"], "images_count": row["images_count"], "candidate_count": row["images_missing_alt_count"], "items": [], "truncated": True, "demo_meta": _dataset_meta(fixture)})
    if method == "GET" and path == "/api/v1/seo/internal-links":
        pages = {row["id"]: row for row in fixture["pages"]}
        edges = deepcopy(fixture["internal_links"])
        incoming = {page_id: 0 for page_id in pages}
        outgoing = {page_id: 0 for page_id in pages}
        for edge in edges:
            outgoing[edge["source"]] += 1
            incoming[edge["target"]] += 1
        nodes = [{
            "id": page_id, "url": row["url"], "title": row["title"],
            "page_type": row.get("page_type"), "incoming": incoming[page_id],
            "outgoing": outgoing[page_id], "orphan": incoming[page_id] == 0,
        } for page_id, row in pages.items()]
        return DemoResponse(200, {"nodes": nodes, "edges": edges, "stats": {"pages": len(nodes), "links": len(edges), "orphans": sum(row["orphan"] for row in nodes)}, "demo_meta": _dataset_meta(fixture)})
    if method == "GET" and path == "/api/v1/seo/backlinks":
        rows = _select(deepcopy(fixture["backlinks"]), query)
        return DemoResponse(200, {"items": rows, "total": len(rows), "stats": {"active": sum(row["status"] == "active" and row.get("verification", {}).get("state") == "found" for row in rows), "pending": sum(row.get("verification", {}).get("state") == "pending" for row in rows), "lost": sum(row["status"] == "lost" for row in rows), "toxic": sum((row.get("toxic_score") or 0) >= 70 for row in rows), "domains": len({row["source_domain"] for row in rows})}, "demo_meta": _dataset_meta(fixture)})
    if method == "GET" and path == "/api/v1/seo/backlinks/discovery-sources":
        rows = deepcopy(fixture["backlink_sources"])
        return DemoResponse(200, {"items": rows, "total": len(rows), "demo_meta": _dataset_meta(fixture)})
    if method == "GET" and path == "/api/v1/seo/backlinks/analysis":
        return DemoResponse(200, _backlink_analysis(fixture))
    if method == "GET" and path == "/api/v1/seo/backlinks/index-status":
        return DemoResponse(200, _demo_provider(fixture) | {"last_query": None})
    if method == "GET" and path == "/api/v1/seo/backlinks/opportunities":
        return DemoResponse(200, {"provider": _demo_provider(fixture), "result": deepcopy(fixture["backlink_opportunities"]), "demo_meta": _dataset_meta(fixture)})
    if method == "GET" and path == "/api/v1/seo/tasks":
        rows = deepcopy(fixture["work_orders"])
        return DemoResponse(200, rows)
    if method == "GET" and path == "/api/v1/seo/backlinks/outcomes":
        provider = _demo_provider(fixture)
        return DemoResponse(200, {"items": deepcopy(fixture["backlink_outcomes"]), "usage": {"provider": provider, "quotas": [{"kind": "backlink_index", "limit_calls_24h": 1, "reserved_calls": 0, "remaining_calls": 1, "attempted_at": None, "next_available_at": None}, {"kind": "backlink_opportunities", "limit_calls_24h": 4, "reserved_calls": 0, "remaining_calls": 4, "attempted_at": None, "next_available_at": None}], "cost": None, "note": "演示身份不会调用外部供应商。"}, "note": "演示中的发布、外链核验与引荐数据分别展示，不作搜索效果归因。", "demo_meta": _dataset_meta(fixture)})
    if method == "GET" and path == "/api/v1/seo/competitors":
        return DemoResponse(200, {"items": deepcopy(fixture["competitors"]), "events": deepcopy(fixture["competitor_events"]), "demo_meta": _dataset_meta(fixture)})
    if method == "GET" and path == "/api/v1/seo/competitors/rankings":
        return DemoResponse(200, {"device": query.get("device") or "desktop", "competitors": deepcopy(fixture["competitors"]), "items": deepcopy(fixture["competitor_rankings"]), "demo_meta": _dataset_meta(fixture)})
    if any(pattern.fullmatch(path) for pattern in _SIMULATED_ACTIONS):
        return DemoResponse(200, {"status": "simulated", "simulated": True, "persisted": False, "side_effects": [], "message": "演示动作已模拟；未写数据库，未触发采集、生成、调度或发布。", "request": deepcopy(dict(body or {})), "demo_meta": _dataset_meta(fixture)})
    return DemoResponse(404, {"detail": "该 SEO 功能尚未接入演示数据层", "code": "seo_static_demo_endpoint_unavailable", "demo_meta": _dataset_meta(fixture)})


def _tenant_from_request(query: Mapping[str, str], body: Mapping[str, Any] | None) -> int | None:
    raw_values = []
    if query.get("tenant_id") is not None:
        raw_values.append(query.get("tenant_id"))
    if body and body.get("tenant_id") is not None:
        raw_values.append(body.get("tenant_id"))
    values = [_int(value) for value in raw_values]
    if any(value is None for value in values):
        raise HTTPException(422, "tenant_id 必须是整数")
    if len(set(values)) > 1:
        raise HTTPException(422, "请求中的 tenant_id 不一致")
    return values[0] if values else None


def _validate_demo_site(query: Mapping[str, str], body: Mapping[str, Any] | None) -> None:
    raw_values = []
    if query.get("site_id") is not None:
        raw_values.append(query.get("site_id"))
    if body and body.get("site_id") is not None:
        raw_values.append(body.get("site_id"))
    values = [_int(value) for value in raw_values]
    if any(value is None for value in values):
        raise HTTPException(422, "site_id 必须是整数")
    if any(value != DEMO_SITE_ID for value in values):
        raise HTTPException(404, "演示网站不存在")


def _required_demo_permission(path: str) -> str:
    if path.rstrip("/") == "/api/v1/seo/sites":
        return "seo.assets"
    if "/alerts" in path:
        return "seo.alerts"
    if "/backlinks" in path or "/internal-links" in path or path.rstrip("/") == "/api/v1/seo/tasks":
        return "seo.links"
    if "/competitors" in path:
        return "seo.competitors"
    if "/content-assets" in path or "/content-distribution" in path:
        return "seo.content"
    if "/keywords" in path or "/rank-" in path:
        return "seo.keywords"
    if "/site-pages" in path or "/site/" in path or "/workbench/sites" in path:
        return "seo.site"
    return "seo.dashboard"


async def _authenticate_demo_request(request: Request) -> AuthContext | None:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    bearer = HTTPAuthorizationCredentials(scheme=scheme, credentials=token)
    async with async_session_factory() as session:
        return await require_auth(bearer=bearer, header_key=None, key=None, session=session)


async def serve_static_demo(request: Request) -> JSONResponse | None:
    """Return a fixture response for the exact demo principal, else ``None``."""
    if not request.url.path.startswith("/api/v1/seo/"):
        return None
    body: dict[str, Any] | None = None
    if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        try:
            candidate = await request.json()
            body = candidate if isinstance(candidate, dict) else None
        except (ValueError, RuntimeError):
            body = None
    try:
        ctx = await _authenticate_demo_request(request)
    except HTTPException:
        # Preserve the existing route's authentication response and behavior.
        return None
    if (
        ctx is None
        or ctx.is_superadmin
        or ctx.username != DEMO_USERNAME
        or ctx.tenant_id != DEMO_TENANT_ID
    ):
        return None
    try:
        tenant_id = _tenant_from_request(request.query_params, body)
        if tenant_id is not None:
            ctx.ensure_tenant(tenant_id)
        _validate_demo_site(request.query_params, body)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    if request.url.path.rstrip("/") == "/api/v1/seo/content-distribution/catalog":
        # This global catalog is already a pure static response with no tenant data.
        return None
    if not ctx.can_view(_required_demo_permission(request.url.path)):
        return JSONResponse(status_code=403, content={"detail": "当前演示身份没有 SEO 只读权限", "code": "seo_static_demo_permission_denied"})
    resolved = resolve_demo_response(request.method, request.url.path, request.query_params, body)
    return JSONResponse(status_code=resolved.status_code, content=resolved.payload)
