"""Deterministic, offline-only GEO demo fixture manifest.

This module deliberately has no database imports and no apply command.  It prepares
reviewable synthetic data while the permanent tenant-level demo guard is pending.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


FIXTURE_NAMESPACE = "g-snipers-geo-demo-v1"
FIXTURE_MARKER = "[全虚拟演示][GEO_DEMO_FIXTURE:g-snipers-geo-demo-v1]"
TENANT_NAME = "G-Snipers 全域演示（全虚拟）"
PROTECTED_TENANT_IDS = (1, 4)
SHANGHAI = ZoneInfo("Asia/Shanghai")

QUESTIONS = (
    "制造企业如何评估智能设备巡检平台？",
    "设备运维知识库应该包含哪些内容？",
    "如何比较不同工业数据分析平台？",
    "工厂预测性维护项目如何开始？",
    "工业设备故障诊断系统有哪些选型指标？",
    "制造业如何建设可追溯的维修知识体系？",
    "多工厂设备健康数据如何统一管理？",
    "设备停机风险如何提前发现？",
    "工业智能运维平台如何验证效果？",
    "设备维保团队如何减少重复排查？",
    "工业知识问答如何控制事实准确性？",
    "采购工业软件时如何验证供应商能力？",
)

ENGINES = (
    ("deepseek", "DeepSeek", "DeepSeek", "deepseek-chat"),
    ("qwen", "通义千问", "Alibaba Cloud", "qwen-max"),
    ("kimi", "Kimi", "Moonshot AI", "kimi-k2.6"),
)

COMPETITORS = ("北辰智造", "远海科技", "恒峰系统")
CHANNELS = ("website", "wechat", "zhihu")
EXPECTED_COUNTS = {
    "tenants": 1,
    "patrol_settings": 1,
    "ai_settings": 1,
    "businesses": 1,
    "units": 3,
    "prompts": 12,
    "tracking_engines": 3,
    "publishing_channels": 3,
    "channel_accounts": 0,
    "optimization_periods": 2,
    "patrol_runs": 2,
    "answer_snapshots": 72,
    "facts": 6,
    "content_tasks": 2,
    "article_versions": 4,
    "channel_variants": 6,
    "publications": 0,
    "action_tickets": 4,
}


def _logical(kind: str, name: str) -> str:
    return f"{FIXTURE_NAMESPACE}:{kind}:{name}"


def _utc_iso(local_day: date, hour: int, minute: int) -> str:
    value = datetime.combine(local_day, time(hour, minute), tzinfo=SHANGHAI)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _snapshot(
    *, week: str, week_start: date, prompt_index: int, engine_index: int
) -> dict[str, Any]:
    engine_key, _, provider, model = ENGINES[engine_index]
    prompt_key = f"q{prompt_index + 1:02d}"
    key = f"{week}:{prompt_key}:{engine_key}"
    current = week == "current"
    mentions = (prompt_index + engine_index) % (2 if current else 3) == 0
    cites_own = (prompt_index + 2 * engine_index) % (3 if current else 6) == 0
    competitors = []
    if (prompt_index + engine_index) % 2 == 0:
        competitors.append(COMPETITORS[0])
    if (prompt_index + engine_index) % 3 == 0:
        competitors.append(COMPETITORS[1])
    if current and (prompt_index + engine_index) % 6 == 0:
        competitors.append(COMPETITORS[2])
    cited_urls = (
        [f"https://g-snipers-demo.invalid/knowledge/{prompt_key}"] if cites_own else []
    )
    answer_parts = [FIXTURE_MARKER, f"虚拟回答样本 {key}。"]
    if mentions:
        answer_parts.append("示例品牌 G-Snipers Demo 被作为候选方案提及。")
    if competitors:
        answer_parts.append("虚拟竞品：" + "、".join(competitors) + "。")
    if cited_urls:
        answer_parts.append("虚拟引用：" + cited_urls[0])
    return {
        "logical_key": _logical("answer", key),
        "prompt_key": _logical("prompt", prompt_key),
        "period_key": _logical("period", week),
        "patrol_run_key": _logical("patrol", week),
        "engine": engine_key,
        "provider": provider,
        "model": model,
        "raw_text": "".join(answer_parts),
        "captured_at": _utc_iso(
            week_start + timedelta(days=1 + prompt_index % 5),
            9 + engine_index * 3,
            prompt_index,
        ),
        "mentions_brand": mentions,
        "cited_urls": cited_urls,
        "competitors": competitors,
        "brand_position": "top3" if mentions else "unknown",
        "sentiment": "neutral",
        "citation_format": "linked" if cited_urls else "none",
        "citation_accuracy": "unknown",
        "sample_mode": "mock_persona",
        "simulated": True,
        "note": (
            f"{FIXTURE_MARKER} method=unprimed_json_v2 analysis=completed "
            "source=offline_manifest never_official=true"
        ),
        "formal_metric_eligible": False,
        "source_classification": "simulated",
        "formal_exclusion_reasons": ["simulated_sample", "snapshot_patrol_mismatch"],
    }


def _raw_week_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    mentions = sum(bool(row["mentions_brand"]) for row in rows)
    own_citations = sum(bool(row["cited_urls"]) for row in rows)
    competitors = Counter(name for row in rows for name in set(row["competitors"]))
    return {
        "sample_count": len(rows),
        "mention_count": mentions,
        "mention_rate": round(mentions * 100 / len(rows), 4),
        "own_domain_citation_count": own_citations,
        "competitor_mentions": dict(sorted(competitors.items())),
    }


def _change(current: float, previous: float) -> dict[str, Any]:
    delta = current - previous
    return {
        "direction": "up" if delta > 0 else "down" if delta < 0 else "flat",
        "change_pct": round(delta / abs(previous) * 100, 4) if previous else None,
        "change_abs": round(delta, 4),
    }


def build_manifest(week_end: date = date(2026, 9, 7)) -> dict[str, Any]:
    """Return a stable logical-key manifest; no database or network access."""
    if week_end.weekday() != 0:
        raise ValueError("week_end must be a Monday in Asia/Shanghai")
    current_start = week_end - timedelta(days=7)
    previous_start = week_end - timedelta(days=14)
    answers = [
        _snapshot(
            week=week,
            week_start=start,
            prompt_index=prompt_index,
            engine_index=engine_index,
        )
        for week, start in (("previous", previous_start), ("current", current_start))
        for prompt_index in range(len(QUESTIONS))
        for engine_index in range(len(ENGINES))
    ]
    answer_by_week = {
        week: [row for row in answers if f":answer:{week}:" in row["logical_key"]]
        for week in ("previous", "current")
    }
    raw_stats = {week: _raw_week_stats(rows) for week, rows in answer_by_week.items()}
    raw_trend = {
        key: _change(raw_stats["current"][key], raw_stats["previous"][key])
        for key in ("mention_count", "mention_rate", "own_domain_citation_count")
    }

    prompts = [
        {
            "logical_key": _logical("prompt", f"q{index + 1:02d}"),
            "question": question,
            "language": "zh-CN",
            "priority": 100 - index,
            "tags": ["全虚拟演示", "GEO_DEMO_FIXTURE"],
            "status": "active",
            "source": "demo_fixture",
            "is_brand_probe": False,
            "unit_key": _logical("unit", f"u{index % 3 + 1}"),
        }
        for index, question in enumerate(QUESTIONS)
    ]
    engines = [
        {
            "logical_key": _logical("engine", key),
            "engine_key": key,
            "display_name": f"{display}（全虚拟演示）",
            "provider": provider,
            "model": model,
            "enabled": False,
            "sample_mode": "mock_persona",
            "api_base_url": None,
            "api_key_encrypted": None,
            "note": f"{FIXTURE_MARKER} disabled=true no_execution=true",
        }
        for key, display, provider, model in ENGINES
    ]
    patrol_runs = []
    patrol_week_starts = {"previous": previous_start, "current": current_start}
    for week in ("previous", "current"):
        rows = answer_by_week[week]
        patrol_start = patrol_week_starts[week]
        patrol_runs.append(
            {
                "logical_key": _logical("patrol", week),
                "status": "completed",
                "trigger": "manual",
                "auto_persist": False,
                "prefer_real": False,
                "started_at": _utc_iso(patrol_start, 0, 0),
                "finished_at": _utc_iso(patrol_start + timedelta(days=7), 0, 0),
                "summary": {
                    "fixture_namespace": FIXTURE_NAMESPACE,
                    "cells_total": len(rows),
                    "cells_ok": len(rows),
                    "cells_fail": 0,
                    "official_metric_eligible": False,
                },
                "items": [
                    {
                        "snapshot_key": row["logical_key"],
                        "prompt_key": row["prompt_key"],
                        "prompt_question": QUESTIONS[
                            int(row["prompt_key"].rsplit("q", 1)[1]) - 1
                        ],
                        "engine": row["engine"],
                        "provider": row["provider"],
                        "model": row["model"],
                        "raw_text": row["raw_text"],
                        "ok": True,
                        "sample_mode": "mock_persona",
                        "simulated": True,
                        "sampling_method": "unprimed_json_v2",
                        "analysis_status": "completed",
                        "suggested_mentions_brand": row["mentions_brand"],
                        "competitors": row["competitors"],
                    }
                    for row in rows
                ],
            }
        )

    facts = [
        {
            "logical_key": _logical("fact", f"f{index + 1}"),
            "title": f"[全虚拟演示] 设备知识事实 {index + 1}",
            "statement": f"{FIXTURE_MARKER} 虚构产品能力说明 {index + 1}，仅用于界面演示。",
            "fact_type": ("product", "metric", "case")[index % 3],
            "source_name": "G-Snipers Demo 虚拟资料库",
            "source_url": f"https://g-snipers-demo.invalid/facts/{index + 1}",
            "trust_level": "needs_review",
            "status": "active",
            "meta": {"fixture_namespace": FIXTURE_NAMESPACE, "synthetic": True},
            "import_batch_id": FIXTURE_NAMESPACE,
        }
        for index in range(6)
    ]
    content_tasks = [
        {
            "logical_key": _logical("content_task", "invalidated"),
            "prompt_key": prompts[0]["logical_key"],
            "business_key": _logical("business", "operations"),
            "period_key": _logical("period", "current"),
            "title": "[全虚拟演示] 旧审核与渠道稿失效",
            "status": "editing",
            "pipeline_step": "article",
            "review_status": "none",
            "target_channels": list(CHANNELS),
            "brief": {
                "fixture_namespace": FIXTURE_NAMESPACE,
                "synthetic": True,
                "scenario": "latest article invalidates prior review and variants",
            },
            "fact_keys": [row["logical_key"] for row in facts[:3]],
        },
        {
            "logical_key": _logical("content_task", "regenerated"),
            "prompt_key": prompts[1]["logical_key"],
            "business_key": _logical("business", "operations"),
            "period_key": _logical("period", "current"),
            "title": "[全虚拟演示] 三渠道稿已重生成",
            "status": "editing",
            "pipeline_step": "variants",
            "review_status": "none",
            "target_channels": list(CHANNELS),
            "brief": {
                "fixture_namespace": FIXTURE_NAMESPACE,
                "synthetic": True,
                "scenario": "variants regenerated against latest article",
            },
            "fact_keys": [row["logical_key"] for row in facts[3:]],
        },
    ]
    articles = []
    variants = []
    for task_name in ("invalidated", "regenerated"):
        for version in (1, 2):
            articles.append(
                {
                    "logical_key": _logical("article", f"{task_name}:v{version}"),
                    "task_key": _logical("content_task", task_name),
                    "version_no": version,
                    "kind": "master",
                    "title": f"{FIXTURE_MARKER} {task_name} V{version}",
                    "body_markdown": (
                        f"# {FIXTURE_MARKER}\n\n这是 {task_name} 的虚拟母稿 V{version}，"
                        "不得用于真实发布。"
                    ),
                    "generation_meta": {
                        "source": "demo_fixture",
                        "from_version": version - 1 or None,
                        "fixture_namespace": FIXTURE_NAMESPACE,
                        "synthetic": True,
                    },
                }
            )
        bound_version = 1 if task_name == "invalidated" else 2
        for channel in CHANNELS:
            variants.append(
                {
                    "logical_key": _logical("variant", f"{task_name}:{channel}"),
                    "task_key": _logical("content_task", task_name),
                    "article_key": _logical("article", f"{task_name}:v{bound_version}"),
                    "channel": channel,
                    "title": f"{FIXTURE_MARKER} {channel} 渠道稿",
                    "body_markdown": f"{FIXTURE_MARKER} 虚拟渠道稿，不得发布。",
                    "status": "draft",
                    "expected_stale": task_name == "invalidated",
                    "adapt_meta": {
                        "fixture_namespace": FIXTURE_NAMESPACE,
                        "synthetic": True,
                        "publishable": False,
                        "quality": "demo_only_not_publishable",
                    },
                }
            )

    tickets = [
        {
            "logical_key": _logical("ticket", f"t{index + 1}"),
            "advice_code": "cockpit:v1:task",
            "title": title,
            "status": status,
            "priority": "medium",
            "action": f"{FIXTURE_MARKER} {action}",
            "acceptance_type": "metric",
            "baseline_snapshot": {
                "fixture_namespace": FIXTURE_NAMESPACE,
                "synthetic": True,
                "official_metric": None,
            },
            "progress_first": {
                "id": _logical("contract_task", f"t{index + 1}"),
                "module": "geo",
                "action_type": "demo_only",
                "params": {"fixture_namespace": FIXTURE_NAMESPACE},
                "created_by": "cockpit",
                "assignee_role": "geo_operator",
            },
            "evidence": [],
            "completion_evidence": None,
        }
        for index, (title, status, action) in enumerate(
            (
                ("[全虚拟演示] 补充可信事实", "todo", "补充真实资料后方可完成"),
                ("[全虚拟演示] 改进内容结构", "doing", "等待真实指标变化"),
                ("[全虚拟演示] 配置发布前置条件", "todo", "保持发布禁用"),
                ("[全虚拟演示] 放弃过期演示动作", "cancelled", "无需完成证据"),
            )
        )
    ]

    entities = {
        "tenants": [
            {
                "logical_key": _logical("tenant", "root"),
                "name": TENANT_NAME,
                "strategy": "demo",
                "industry": "工业智能运维（全虚拟演示）",
                "business_desc": FIXTURE_MARKER,
                "brand_terms": ["G-Snipers Demo"],
                "physical_id": None,
            }
        ],
        "patrol_settings": [
            {
                "tenant_key": _logical("tenant", "root"),
                "enabled": False,
                "auto_persist": False,
                "prefer_real": False,
                "prompt_limit": 0,
                "engine_keys": [],
            }
        ],
        "ai_settings": [
            {
                "tenant_key": _logical("tenant", "root"),
                "provider": "offline_demo",
                "base_url": "https://demo.invalid",
                "model": "none",
                "api_key_encrypted": None,
                "enabled": False,
                "monitoring_stance": "simulation",
                "note": f"{FIXTURE_MARKER} no_execution=true",
            }
        ],
        "businesses": [
            {
                "logical_key": _logical("business", "operations"),
                "name": "[全虚拟演示] 智能设备运维",
                "description": FIXTURE_MARKER,
                "status": "active",
                "profile": {
                    "product_name": "G-Snipers Demo",
                    "brand_description": "全虚拟工业智能运维演示品牌",
                    "fixture_namespace": FIXTURE_NAMESPACE,
                    "synthetic": True,
                },
            }
        ],
        "units": [
            {
                "logical_key": _logical("unit", f"u{index + 1}"),
                "business_key": _logical("business", "operations"),
                "name": f"[全虚拟演示] 主题单元 {index + 1}",
                "keyword": ("设备巡检", "预测维护", "工业知识库")[index],
                "status": "active",
            }
            for index in range(3)
        ],
        "prompts": prompts,
        "tracking_engines": engines,
        "publishing_channels": [
            {
                "logical_key": _logical("publishing_channel", channel),
                "name": f"[全虚拟演示] {channel}",
                "channel_type": channel,
                "publish_mode": "manual_only",
                "base_url": "https://g-snipers-demo.invalid" if channel == "website" else None,
                "enabled": False,
                "content_rules": {
                    "fixture_namespace": FIXTURE_NAMESPACE,
                    "synthetic": True,
                    "publish_disabled": True,
                },
            }
            for channel in CHANNELS
        ],
        "channel_accounts": [],
        "optimization_periods": [
            {
                "logical_key": _logical("period", week),
                "name": f"[全虚拟演示] {week} 完整自然周",
                "business_key": _logical("business", "operations"),
                "starts_at": _utc_iso(start, 0, 0),
                "ends_at": _utc_iso(start + timedelta(days=7), 0, 0),
                "status": "closed",
                "baseline_meta": {"fixture_namespace": FIXTURE_NAMESPACE, "synthetic": True},
                "result_meta": {"fixture_namespace": FIXTURE_NAMESPACE, "synthetic": True},
                "publication_ids": [],
            }
            for week, start in (("previous", previous_start), ("current", current_start))
        ],
        "patrol_runs": patrol_runs,
        "answer_snapshots": answers,
        "facts": facts,
        "content_tasks": content_tasks,
        "article_versions": articles,
        "channel_variants": variants,
        "publications": [],
        "action_tickets": tickets,
    }
    counts = {name: len(rows) for name, rows in entities.items()}
    return {
        "fixture": {
            "namespace": FIXTURE_NAMESPACE,
            "marker": FIXTURE_MARKER,
            "schema_version": 1,
            "offline_only": True,
            "database_apply_supported": False,
            "protected_tenant_ids": list(PROTECTED_TENANT_IDS),
            "id_strategy": "database IDs unresolved; upsert by namespace + logical_key only",
            "cleanup_strategy": "delete only rows resolved from this namespace, child-first, then dedicated tenant",
            "load_order": [
                "tenant and GEO entitlement",
                "fixture tenant registry",
                "settings, business, units, prompts, engines, channels, periods, facts",
                "patrol runs and answer snapshots",
                "content tasks, task facts, article versions, variants, tickets",
            ],
            "cleanup_order": [
                "publications, variants, article versions, task facts, content tasks",
                "tickets, snapshots, patrol runs, periods",
                "facts, prompts, units, business",
                "accounts, channels, engines, settings, entitlement, tenant",
            ],
        },
        "time_contract": {
            "timezone": "Asia/Shanghai",
            "week_end": week_end.isoformat(),
            "previous": {"start": previous_start.isoformat(), "end": current_start.isoformat()},
            "current": {"start": current_start.isoformat(), "end": week_end.isoformat()},
        },
        "entities": entities,
        "counts": counts,
        "expectations": {
            "demo_only_raw_comparison": {
                "label": "illustrative synthetic values; never official metrics",
                "previous": raw_stats["previous"],
                "current": raw_stats["current"],
                "trend_7d": raw_trend,
            },
            "official_metrics": {
                "geo.visibility.ai_mention_count_7d": {"value": None, "trend_7d": None},
                "geo.visibility.ai_mention_rate_7d": {"value": None, "trend_7d": None},
                "geo.visibility.ai_visibility_score": {"value": None, "trend_7d": None},
                "answer_exclusion_reasons": ["simulated_sample", "snapshot_patrol_mismatch"],
                "period_reason_codes": [
                    "insufficient_samples",
                    "insufficient_questions",
                    "insufficient_engines",
                ],
                "score_extra_reason_codes": ["missing_own_domain"],
            },
            "scheduler_eligible": False,
            "real_collection_enabled": False,
            "generation_enabled": False,
            "publishing_enabled": False,
            "completion_evidence_available": False,
        },
        "read_interfaces": [
            "/api/v1/geo/integration/read/questions",
            "/api/v1/geo/integration/read/answers",
            "/api/v1/geo/integration/read/simulate-action",
            "/api/v1/geo/integration/read/period-context",
            "/api/v1/geo/integration/read/capabilities",
            "/api/v1/geo/integration/read/content-tasks",
            "/api/v1/geo/integration/read/content-tasks/{id}",
            "/api/v1/geo/integration/read/patrol-runs/{id}",
            "/api/v1/geo/integration/metrics/snapshot",
            "/api/v1/geo/integration/metrics/dictionary",
            "/api/v1/geo/integration/tasks",
        ],
    }


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors = []
    fixture = manifest.get("fixture") or {}
    entities = manifest.get("entities") or {}
    if fixture.get("database_apply_supported") is not False:
        errors.append("database apply must remain disabled")
    if set(fixture.get("protected_tenant_ids") or ()) != set(PROTECTED_TENANT_IDS):
        errors.append("protected tenant IDs changed")
    keys = [
        row["logical_key"]
        for rows in entities.values()
        for row in rows
        if isinstance(row, dict) and row.get("logical_key")
    ]
    if len(keys) != len(set(keys)):
        errors.append("logical keys must be globally unique")
    if manifest.get("counts") != EXPECTED_COUNTS:
        errors.append("entity counts changed")
    key_set = set(keys)

    def check_references(value: Any, path: str = "root") -> None:
        if isinstance(value, dict):
            for field, child in value.items():
                child_path = f"{path}.{field}"
                if field != "logical_key" and field.endswith("_key") and isinstance(child, str):
                    if child.startswith(FIXTURE_NAMESPACE + ":") and child not in key_set:
                        errors.append(f"unresolved logical reference: {child_path}={child}")
                elif field.endswith("_keys") and isinstance(child, list):
                    for ref_key in child:
                        if isinstance(ref_key, str) and ref_key.startswith(FIXTURE_NAMESPACE + ":") and ref_key not in key_set:
                            errors.append(f"unresolved logical reference: {child_path}={ref_key}")
                check_references(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                check_references(child, f"{path}[{index}]")

    check_references(entities, "entities")
    answers = entities.get("answer_snapshots") or []
    if len(answers) != 72:
        errors.append("expected exactly 72 answer snapshots")
    for row in answers:
        if not row.get("simulated") or row.get("sample_mode") != "mock_persona":
            errors.append(f"answer is not forced simulated: {row.get('logical_key')}")
        if FIXTURE_MARKER not in str(row.get("raw_text")) or FIXTURE_MARKER not in str(row.get("note")):
            errors.append(f"answer lacks visible fixture marker: {row.get('logical_key')}")
        if row.get("formal_metric_eligible") is not False:
            errors.append(f"answer may enter formal metrics: {row.get('logical_key')}")
    if any(row.get("enabled") for row in entities.get("tracking_engines") or []):
        errors.append("tracking engines must be disabled")
    if any(row.get("api_key_encrypted") is not None for row in entities.get("tracking_engines") or []):
        errors.append("tracking engines must not contain credentials")
    if any(row.get("enabled") for row in entities.get("publishing_channels") or []):
        errors.append("publishing channels must be disabled")
    if entities.get("channel_accounts") or entities.get("publications"):
        errors.append("accounts and publications must be empty")
    if any(row.get("adapt_meta", {}).get("publishable") is not False for row in entities.get("channel_variants") or []):
        errors.append("every variant must be explicitly non-publishable")
    settings = entities.get("patrol_settings") or []
    if len(settings) != 1 or settings[0].get("enabled") is not False:
        errors.append("scheduler settings must exist and be disabled")
    if any(ticket.get("status") == "done" for ticket in entities.get("action_tickets") or []):
        errors.append("synthetic tickets cannot be completed with fake evidence")
    if manifest.get("expectations", {}).get("official_metrics", {}).get(
        "geo.visibility.ai_mention_count_7d", {}
    ).get("value") is not None:
        errors.append("official metric expectation must be null")
    return errors


def canonical_json(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def manifest_digest(manifest: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(manifest).encode()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the offline GEO demo fixture manifest")
    parser.add_argument("command", choices=("plan", "validate", "digest"), nargs="?", default="validate")
    parser.add_argument("--week-end", type=date.fromisoformat, default=date(2026, 9, 7))
    args = parser.parse_args(argv)
    manifest = build_manifest(args.week_end)
    errors = validate_manifest(manifest)
    if args.command == "plan":
        print(canonical_json(manifest), end="")
    elif args.command == "digest":
        print(manifest_digest(manifest))
    else:
        print(json.dumps({"valid": not errors, "errors": errors, "counts": manifest["counts"]}, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
