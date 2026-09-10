"""Embedded, query-only GEO demo adapter for the dedicated tenant 16 account.

The adapter is intentionally independent of the database and network.  It maps
the reviewed offline fixture manifest onto the existing cockpit read shapes.
Synthetic values are always visibly labelled and never returned as official
metrics or completion evidence.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.geo.demo_fixture_manifest import build_manifest


DEMO_TENANT_ID = 16
DEMO_USER_ID = 5
DEMO_USERNAME = "workbench_test_readonly"
DEMO_DATASET_VERSION = "tenant16-geo-demo-v2"
DEMO_WEEK_END = date(2026, 9, 7)
DEMO_ID_BASE = 16_000_000
SHANGHAI = ZoneInfo("Asia/Shanghai")


def is_tenant16_demo(ctx: Any, tenant_id: int) -> bool:
    """Only the dedicated, tenant-bound test identity receives synthetic data."""
    return (
        tenant_id == DEMO_TENANT_ID
        and getattr(ctx, "user_id", None) == DEMO_USER_ID
        and getattr(ctx, "username", None) == DEMO_USERNAME
        and getattr(ctx, "tenant_id", None) == DEMO_TENANT_ID
        and not getattr(ctx, "is_superadmin", False)
    )


def is_demo_tenant(tenant_id: int) -> bool:
    return tenant_id == DEMO_TENANT_ID


def metadata() -> dict[str, Any]:
    return {
        "enabled": True,
        "official": False,
        "source_kind": "synthetic",
        "dataset_version": DEMO_DATASET_VERSION,
        "read_only": True,
        "execution_mode": "simulated_result_only",
        "excluded_from_official_metrics": True,
    }


class Tenant16DemoSession:
    """Sentinel proving adapter responses cannot accidentally query or write."""

    info = {
        "geo_control_tenant_id": DEMO_TENANT_ID,
        "geo_data_tenant_id": DEMO_TENANT_ID,
        "geo_tenant16_embedded_demo": True,
    }

    def __getattr__(self, name: str):
        raise AssertionError(f"tenant 16 embedded demo attempted database operation: {name}")


def _ref(kind: str, ident: int) -> dict[str, Any]:
    return {"module": "geo", "type": kind, "id": ident}


def _id_map(rows: list[dict[str, Any]], offset: int) -> dict[str, int]:
    return {row["logical_key"]: DEMO_ID_BASE + offset + index for index, row in enumerate(rows, 1)}


@lru_cache(maxsize=1)
def _dataset() -> dict[str, Any]:
    manifest = build_manifest(DEMO_WEEK_END)
    entities = manifest["entities"]
    prompt_ids = _id_map(entities["prompts"], 1_000)
    answer_ids = _id_map(entities["answer_snapshots"], 10_000)
    run_ids = _id_map(entities["patrol_runs"], 20_000)
    task_ids = _id_map(entities["content_tasks"], 30_000)
    article_ids = _id_map(entities["article_versions"], 40_000)
    variant_ids = _id_map(entities["channel_variants"], 50_000)
    ticket_ids = _id_map(entities["action_tickets"], 60_000)
    return {
        "manifest": manifest,
        "prompt_ids": prompt_ids,
        "answer_ids": answer_ids,
        "run_ids": run_ids,
        "task_ids": task_ids,
        "article_ids": article_ids,
        "variant_ids": variant_ids,
        "ticket_ids": ticket_ids,
    }


def _base() -> dict[str, Any]:
    return {
        "tenant_id": DEMO_TENANT_ID,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "timezone": "Asia/Shanghai",
        "demo": metadata(),
    }


def question_page(*, limit: int, before_id: int | None = None, status: str | None = None,
                  is_brand_probe: bool | None = None) -> dict[str, Any]:
    data = _dataset()
    rows = data["manifest"]["entities"]["prompts"]
    items = []
    for row in reversed(rows):
        ident = data["prompt_ids"][row["logical_key"]]
        if before_id is not None and ident >= before_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if is_brand_probe is not None and row["is_brand_probe"] != is_brand_probe:
            continue
        timestamp = f"{DEMO_WEEK_END.isoformat()}T00:00:00Z"
        items.append({
            "ref": _ref("question", ident),
            "current_text": row["question"],
            "language": row["language"],
            "status": row["status"],
            "question_source": "demo_fixture",
            "question_group": "全域演示问题",
            "market": "CN",
            "is_brand_probe": row["is_brand_probe"],
            "priority": row["priority"],
            "tags": row["tags"],
            "unit_ref": None,
            "business_ref": None,
            "created_at": timestamp,
            "updated_at": timestamp,
            "timestamp_source_timezone": "unknown",
            "source_classification": "simulated",
            "formal_metric_eligible": False,
        })
    page = items[:limit]
    result = _base()
    result.update({
        "pagination": {"limit": limit, "has_more": len(items) > limit,
                       "next_before_id": page[-1]["ref"]["id"] if len(items) > limit and page else None},
        "items": page,
    })
    return result


def _answer_item(row: dict[str, Any], *, detail: bool = False) -> dict[str, Any]:
    data = _dataset()
    snapshot_id = data["answer_ids"][row["logical_key"]]
    prompt_id = data["prompt_ids"][row["prompt_key"]]
    prompt_text = next(p["question"] for p in data["manifest"]["entities"]["prompts"]
                       if p["logical_key"] == row["prompt_key"])
    run_id = data["run_ids"][row["patrol_run_key"]]
    is_current = ":answer:current:" in row["logical_key"]
    item = {
        "ref": _ref("answer_snapshot", snapshot_id),
        "question": {"id": prompt_id, "historical_text": prompt_text,
                     "current_text": prompt_text, "historical_text_source": "demo_fixture"},
        "engine": {"key": row["engine"], "provider": row["provider"], "model": row["model"],
                   "model_revision": None, "metadata_source": "demo_fixture"},
        "captured_at": row["captured_at"],
        "captured_at_local": datetime.fromisoformat(row["captured_at"].replace("Z", "+00:00")).astimezone(SHANGHAI).isoformat(),
        "time_basis": "stored_utc",
        "source": {"kind": "simulated", "stored_sample_mode": "mock_persona", "simulated": True,
                   "sampling_method": "unprimed_json_v2", "analysis_status": "completed",
                   "verified_server_record": False},
        "source_kind": "simulated", "sample_mode": "mock_persona", "simulated": True,
        "answer_excerpt": row["raw_text"][:300],
        "mentions_brand": row["mentions_brand"],
        "cited_urls": row["cited_urls"],
        "competitors": row["competitors"],
        "sample_eligibility": {"eligible": False, "reasons": [{"code": "simulated_sample", "scope": "sample"}]},
        "week_membership": {"within_window": is_current, "included_in_cohort": False,
                            "reasons": [{"code": "simulated_sample", "scope": "sample"}]},
        "metric_adoption": [{"metric_key": "geo.visibility.ai_mention_count_7d", "status": "excluded",
                             "reasons": [{"code": "simulated_sample", "scope": "sample"}]}],
        "comparison_metadata": {"complete": True, "reason_codes": [],
                                "model_identity_basis": "demo_fixture", "exact_model_revision_known": False},
        "relations": [{"relation": "captured_by", "target": _ref("patrol_run", run_id)}],
        "detail_url": f"/api/v1/geo/integration/read/answers/{snapshot_id}?tenant_id=16&week_end={DEMO_WEEK_END}",
        "formal_metric_eligible": False,
        "formal_exclusion_reasons": row["formal_exclusion_reasons"],
    }
    if detail:
        item["raw_text"] = row["raw_text"]
        item["note"] = row["note"]
    else:
        item["raw_text"] = row["raw_text"]
    return item


def answer_page(*, limit: int, prompt_id: int | None = None, engine_key: str | None = None,
                patrol_run_id: int | None = None, source_kind: str | None = None,
                captured_from: datetime | None = None, captured_to: datetime | None = None,
                before_id: int | None = None) -> dict[str, Any]:
    data = _dataset()
    rows = list(reversed(data["manifest"]["entities"]["answer_snapshots"]))
    filtered = []
    for row in rows:
        snapshot_id = data["answer_ids"][row["logical_key"]]
        if before_id is not None and snapshot_id >= before_id:
            continue
        if prompt_id is not None and data["prompt_ids"][row["prompt_key"]] != prompt_id:
            continue
        if engine_key is not None and row["engine"] != engine_key:
            continue
        if patrol_run_id is not None and data["run_ids"][row["patrol_run_key"]] != patrol_run_id:
            continue
        if source_kind is not None and source_kind != "simulated":
            continue
        captured = datetime.fromisoformat(row["captured_at"].replace("Z", "+00:00"))
        if captured_from is not None and captured < captured_from.astimezone(timezone.utc):
            continue
        if captured_to is not None and captured >= captured_to.astimezone(timezone.utc):
            continue
        filtered.append(row)
    page = filtered[:limit]
    result = _base()
    result.update({
        "official_week_end": DEMO_WEEK_END.isoformat(),
        "observation_window": {"start": captured_from.isoformat() if captured_from else None,
                               "end": captured_to.isoformat() if captured_to else None},
        "unknown_time_count": 0,
        "period_context_url": f"/api/v1/geo/integration/read/period-context?tenant_id=16&week_end={DEMO_WEEK_END}",
        "pagination": {"limit": limit, "has_more": len(filtered) > limit, "next_cursor": None,
                       "watermark_max_id": max(data["answer_ids"].values())},
        "items": [_answer_item(row) for row in page],
    })
    return result


def answer_detail(snapshot_id: int) -> dict[str, Any]:
    data = _dataset()
    by_id = {data["answer_ids"][r["logical_key"]]: r for r in data["manifest"]["entities"]["answer_snapshots"]}
    row = by_id.get(snapshot_id)
    if row is None:
        raise HTTPException(404, "对象不存在")
    result = _base()
    result.update({"official_week_end": DEMO_WEEK_END.isoformat(),
                   "period_context_url": f"/api/v1/geo/integration/read/period-context?tenant_id=16&week_end={DEMO_WEEK_END}",
                   "item": _answer_item(row, detail=True)})
    return result


def capabilities() -> dict[str, Any]:
    data = _dataset()
    result = _base()
    result.update({
        "read_only": True,
        "engines": [{"engine_key": r["engine_key"], "display_name": r["display_name"], "enabled": False,
                     "stored_sample_mode": "mock_persona", "configured": False, "effective_mode": "simulated",
                     "configured_mode": "mock_persona", "connection_verified": False, "may_fallback": False,
                     "provider": r["provider"], "historical_model": r["model"],
                     "reason_codes": ["embedded_demo_no_credentials"]}
                    for r in data["manifest"]["entities"]["tracking_engines"]],
        "historical_engine_keys": [r["engine_key"] for r in data["manifest"]["entities"]["tracking_engines"]],
        "channels": [], "configuration_status": "demo_fixture", "actions_enabled": False,
        "note": "全虚拟演示：不试连、不采集、不初始化配置。",
    })
    return result


def demo_summary() -> dict[str, Any]:
    data = _dataset()
    comparison = deepcopy(data["manifest"]["expectations"]["demo_only_raw_comparison"])
    result = _base()
    result.update({
        "official": False, "source_kind": "synthetic", "excluded_from_official_metrics": True,
        "exclusion_reason": {"code": "simulated_sample", "message": "演示样本不进入正式指标或完成证据"},
        "dataset": {"key": "tenant16_embedded_geo_demo", "version": DEMO_DATASET_VERSION,
                    "fixture_namespace": data["manifest"]["fixture"]["namespace"]},
        "window": {"previous": {**data["manifest"]["time_contract"]["previous"], **comparison["previous"]},
                   "current": {**data["manifest"]["time_contract"]["current"], **comparison["current"]}},
        "trend_7d": comparison["trend_7d"],
        "official_metrics_url": f"/api/v1/geo/integration/metrics/snapshot?tenant_id=16&week_end={DEMO_WEEK_END}",
    })
    return result


def period_context() -> dict[str, Any]:
    summary = demo_summary()
    reason = {"code": "simulated_sample", "scope": "week", "message": "演示样本不进入正式指标"}
    return {**_base(), "week_end": DEMO_WEEK_END.isoformat(), "official": False,
            "current": {"start": summary["window"]["current"]["start"],
                        "end": summary["window"]["current"]["end"], "closed": True,
                        "status": "unavailable", "qualified_counts": {"samples": 0, "questions": 0, "engines": 0},
                        "reasons": [reason]},
            "previous": {"start": summary["window"]["previous"]["start"],
                         "end": summary["window"]["previous"]["end"], "closed": True,
                         "status": "unavailable", "qualified_counts": {"samples": 0, "questions": 0, "engines": 0},
                         "reasons": [reason]},
            "minimum_counts": {"samples": 8, "questions": 3, "engines": 2},
            "own_domain_configured": False,
            "metric_status": [{"metric_key": key, "status": "unavailable", "reason_codes": ["simulated_sample"]}
                              for key in ("geo.visibility.ai_mention_count_7d",
                                          "geo.visibility.ai_visibility_score",
                                          "geo.visibility.ai_mention_rate_7d")],
            "comparison": {"comparable": False, "checks": {}, "reason_codes": ["simulated_sample"]},
            "metrics_url": f"/api/v1/geo/integration/metrics/snapshot?tenant_id=16&week_end={DEMO_WEEK_END}",
            "dictionary_url": f"/api/v1/geo/integration/metrics/dictionary?tenant_id=16&week_end={DEMO_WEEK_END}",
            "sample_source": "synthetic", "formal_metrics": None,
            "demo_comparison": {"window": summary["window"], "trend_7d": summary["trend_7d"]},
            "reason_codes": ["simulated_sample"]}


def scheduler_eligibility() -> dict[str, Any]:
    return {**_base(), "read_only": True, "patrol_settings": {"exists": True, "enabled": False},
            "active_prompt_count": 12, "scheduler_eligible": False, "execution_blocked": True,
            "execution_block_reason": "tenant16_embedded_demo_read_only",
            "selection_basis": "embedded_fixture", "selection_stage": "disabled",
            "active_prompts_affect_selection": False, "run_creation_guaranteed": False}


def content_task_list(*, limit: int, before_id: int | None = None) -> dict[str, Any]:
    data = _dataset()
    tasks = []
    for row in reversed(data["manifest"]["entities"]["content_tasks"]):
        ident = data["task_ids"][row["logical_key"]]
        if before_id is not None and ident >= before_id:
            continue
        tasks.append({"ref": _ref("content_task", ident), "title": row["title"],
                      "stored_status": row["status"], "review_status": row["review_status"],
                      "pipeline_step": row["pipeline_step"], "demo": metadata()})
    page = tasks[:limit]
    return {**_base(), "items": page,
            "pagination": {"limit": limit, "has_more": len(tasks) > limit,
                           "next_before_id": page[-1]["ref"]["id"] if len(tasks) > limit and page else None}}


def content_task_detail(task_id: int) -> dict[str, Any]:
    data = _dataset()
    rows = data["manifest"]["entities"]
    by_id = {data["task_ids"][r["logical_key"]]: r for r in rows["content_tasks"]}
    task = by_id.get(task_id)
    if task is None:
        raise HTTPException(404, "对象不存在")
    articles = [r for r in rows["article_versions"] if r["task_key"] == task["logical_key"]]
    versions = [{"ref": _ref("article_version", data["article_ids"][r["logical_key"]]),
                 "version_no": r["version_no"], "title": r["title"],
                 "source": r["generation_meta"]["source"], "from_version": r["generation_meta"]["from_version"],
                 "created_at": f"{DEMO_WEEK_END.isoformat()}T00:00:00Z", "relations": []}
                for r in sorted(articles, key=lambda value: value["version_no"], reverse=True)]
    variants = [r for r in rows["channel_variants"] if r["task_key"] == task["logical_key"]]
    latest = next((r for r in articles if r["version_no"] == max(a["version_no"] for a in articles)), None)
    return {**_base(), "ref": _ref("content_task", task_id), "title": task["title"],
            "stored_status": task["status"], "review_status": task["review_status"], "brief": task["brief"],
            "article": ({**versions[0], "body_markdown": latest["body_markdown"]} if latest else None),
            "versions": versions,
            "variants": [{"ref": _ref("channel_variant", data["variant_ids"][r["logical_key"]]),
                          "article_ref": _ref("article_version", data["article_ids"][r["article_key"]]),
                          "channel": r["channel"], "stored_status": "stale" if r["expected_stale"] else r["status"],
                          "publishable": False} for r in variants],
            "publications": [], "relations": [], "demo": metadata()}


def patrol_list(*, limit: int, before_id: int | None = None) -> dict[str, Any]:
    data = _dataset()
    items = []
    for row in reversed(data["manifest"]["entities"]["patrol_runs"]):
        ident = data["run_ids"][row["logical_key"]]
        if before_id is not None and ident >= before_id:
            continue
        items.append({**_base(), "ref": _ref("patrol_run", ident), "stored_status": "completed",
                      "stale": False, "error": None, "summary": row["summary"], "progress_pct": 100,
                      "relations": [], "result_refs": [], "demo": metadata()})
    return {**_base(), "items": items[:limit], "next_before_id": None}


def patrol_detail(run_id: int) -> dict[str, Any]:
    page = patrol_list(limit=50)
    item = next((row for row in page["items"] if row["ref"]["id"] == run_id), None)
    if item is None:
        raise HTTPException(404, "对象不存在")
    return item


def async_job_list() -> dict[str, Any]:
    return {**_base(), "items": [], "next_before_id": None,
            "note": "演示账号不创建异步生成任务"}
