"""Build a deterministic, offline-only SEM demonstration data bundle.

This module deliberately has no database, HTTP, scheduler, Baidu, or writeback
imports.  It emits inert JSON for review and adapter development; it cannot seed
an environment by itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any


FIXTURE_KEY = "gsnipers-sem-demo-v1"
DEFAULT_END_DATE = date(2026, 9, 8)
TENANT_ID = 990_000_001
ACCOUNT_IDS = (990_000_101, 990_000_102)
PROTECTED_TENANT_IDS = frozenset({4})
REGIONS = ("北京", "上海", "广东", "浙江")
HOURS = (0, 6, 9, 11, 14, 17, 20, 23)
TABLE_ID_BASES = {
    "tenant_modules": 990_000_201,
    "campaigns": 990_001_001,
    "adgroups": 990_002_001,
    "keywords": 990_003_001,
    "kw_report_snapshots": 1_100_000_001,
    "keyword_region_reports": 1_110_000_001,
    "keyword_hourly_reports": 1_120_000_001,
    "search_term_reports": 1_130_000_001,
    "alerts": 1_140_000_001,
    "sem_tasks": 1_150_000_001,
    "operation_records": 1_160_000_001,
}


def _iso_stamp(day: date, hour: int = 3) -> str:
    return datetime.combine(day, time(hour, 0), tzinfo=timezone.utc).isoformat()


def _metric(impression: int, click: int, cost: float) -> dict[str, Any]:
    return {
        "impression": impression,
        "click": click,
        "cost": round(cost, 2),
        "ctr": round(click / impression, 6) if impression else None,
        "cpc": round(cost / click, 2) if click else None,
    }


def _ids(index: int) -> tuple[int, int, int, int]:
    account = ACCOUNT_IDS[index // 12]
    campaign = 990_010_001 + (index // 6)
    adgroup = 990_020_001 + (index // 3)
    keyword = 990_100_001 + index
    return account, campaign, adgroup, keyword


def _keyword_name(index: int) -> str:
    topics = (
        "企业获客系统", "全域营销方案", "搜索推广优化", "品牌增长服务",
        "工业设备询价", "企业数字营销", "精准获客平台", "营销数据分析",
        "百度推广代运营", "广告预算优化", "搜索词分析", "线索增长方案",
        "区域推广服务", "移动端推广", "高意向客户获取", "营销自动化",
        "低成本获客", "推广效果分析", "企业推广咨询", "零点击诊断",
        "缺报演示关键词一", "缺报演示关键词二", "无报告演示关键词", "长尾获客演示",
    )
    return topics[index]


def build_bundle(end_date: date = DEFAULT_END_DATE) -> dict[str, Any]:
    start_date = end_date - timedelta(days=89)
    campaigns = []
    adgroups = []
    keywords = []
    for campaign_index in range(4):
        account = ACCOUNT_IDS[campaign_index // 2]
        campaigns.append({
            "tenant_id": TENANT_ID,
            "baidu_account_id": account,
            "campaign_id": 990_010_001 + campaign_index,
            "campaign_name": f"【虚拟演示】获客计划 {campaign_index + 1}",
            "budget": 600 if campaign_index == 0 else 900,
            "pause": False,
            "equipment_type": 0,
            "region_target": list(REGIONS),
            "schedule": [{"weekday": day, "hours": [9, 10, 11, 14, 15, 16, 20]} for day in range(1, 6)],
            "synced_at": _iso_stamp(end_date),
            "fixture_key": FIXTURE_KEY,
        })
    for adgroup_index in range(8):
        account = ACCOUNT_IDS[adgroup_index // 4]
        adgroups.append({
            "tenant_id": TENANT_ID,
            "baidu_account_id": account,
            "adgroup_id": 990_020_001 + adgroup_index,
            "campaign_id": 990_010_001 + (adgroup_index // 2),
            "adgroup_name": f"【虚拟演示】推广单元 {adgroup_index + 1}",
            "max_price": round(8.5 + adgroup_index * 0.4, 2),
            "pause": False,
            "synced_at": _iso_stamp(end_date),
            "fixture_key": FIXTURE_KEY,
        })
    for index in range(24):
        account, campaign, adgroup, keyword = _ids(index)
        keywords.append({
            "tenant_id": TENANT_ID,
            "baidu_account_id": account,
            "keyword_id": keyword,
            "keyword": _keyword_name(index),
            "campaign_id": campaign,
            "adgroup_id": adgroup,
            "match_type": index % 3,
            "price": round(5.8 + (index % 7) * 0.55, 2),
            "pause": index == 23,
            "quality": 3 - (index % 3),
            "category": ("brand", "focus", "normal", "longtail")[index % 4],
            "category_source": "manual" if index % 6 == 0 else "auto",
            "first_seen_date": start_date.isoformat(),
            "synced_at": _iso_stamp(end_date),
            "fixture_key": FIXTURE_KEY,
        })

    snapshots: list[dict[str, Any]] = []
    for index, keyword_row in enumerate(keywords):
        if index == 22:  # Asset exists but no report rows at all.
            continue
        for day_offset in range(90):
            report_date = start_date + timedelta(days=day_offset)
            if index in {20, 21} and day_offset >= 83:  # Explicit missing-report window.
                continue
            for device in (0, 1):
                account, campaign, adgroup, keyword = _ids(index)
                if index == 19 and day_offset == 77:
                    metric = _metric(0, 0, 0.0)  # Stored row proves a real zero.
                else:
                    growth = 1 + day_offset * 0.006
                    base = 34 + (index % 6) * 7 + device * 11
                    factor = 0.32 if index in {6, 7, 8, 9} and day_offset >= 83 else 1.0
                    impression = int(base * growth * factor)
                    click = max(0, round(impression * (0.035 + (index % 4) * 0.006)))
                    cpc = 6.2 + (index % 5) * 0.9
                    if campaign == 990_010_001 and day_offset >= 80:
                        cpc *= 1.75  # Budget-pressure scenario.
                    metric = _metric(impression, click, click * cpc)
                raw: dict[str, Any] = {"fixture": FIXTURE_KEY, "synthetic": True}
                if index < 8:
                    raw["ocpcConversionsDetail2"] = 1 if metric["click"] >= 3 and day_offset % 9 == 0 else 0
                elif index < 12:
                    if device == 0:
                        raw["ocpcConversionsDetail2"] = 1 if day_offset % 15 == 0 else 0
                elif index < 16:
                    raw["ocpcConversionsDetail2"] = "unavailable"
                snapshots.append({
                    "tenant_id": TENANT_ID,
                    "baidu_account_id": account,
                    "report_date": report_date.isoformat(),
                    "campaign_id": campaign,
                    "campaign_name": next(row["campaign_name"] for row in campaigns if row["campaign_id"] == campaign),
                    "adgroup_id": adgroup,
                    "adgroup_name": next(row["adgroup_name"] for row in adgroups if row["adgroup_id"] == adgroup),
                    "keyword_id": keyword,
                    "keyword": keyword_row["keyword"],
                    "device": device,
                    **metric,
                    "conversions": raw.get("ocpcConversionsDetail2", 0) if isinstance(raw.get("ocpcConversionsDetail2", 0), int) else 0,
                    "raw_metrics": raw,
                    "fetched_at": _iso_stamp(end_date),
                    "fixture_key": FIXTURE_KEY,
                })

    region_reports: list[dict[str, Any]] = []
    hourly_reports: list[dict[str, Any]] = []
    for index in range(12):
        account, campaign, adgroup, keyword = _ids(index)
        for offset in range(14):
            report_date = end_date - timedelta(days=13 - offset)
            for device in (0, 1):
                for region_index, region in enumerate(REGIONS):
                    impression = 18 + index * 2 + region_index * 5 + device * 3
                    click = round(impression * (0.035 + region_index * 0.004))
                    region_reports.append({
                        "tenant_id": TENANT_ID, "baidu_account_id": account,
                        "report_date": report_date.isoformat(), "campaign_id": campaign,
                        "adgroup_id": adgroup, "keyword_id": keyword,
                        "keyword": _keyword_name(index), "device": device,
                        "region_name": region, "region_level": "province",
                        **_metric(impression, click, click * (6.8 + index % 4)),
                        "raw_metrics": {"fixture": FIXTURE_KEY, "synthetic": True},
                        "fetched_at": _iso_stamp(end_date), "fixture_key": FIXTURE_KEY,
                    })
                for hour_index, hour in enumerate(HOURS):
                    impression = 4 + index + (8 if hour in {9, 11, 14, 17} else 1)
                    click = round(impression * (0.03 + (hour_index % 3) * 0.01))
                    hourly_reports.append({
                        "tenant_id": TENANT_ID, "baidu_account_id": account,
                        "report_datetime": f"{report_date.isoformat()}T{hour:02d}:00:00",
                        "report_date": report_date.isoformat(), "hour": hour,
                        "campaign_id": campaign, "adgroup_id": adgroup,
                        "keyword_id": keyword, "keyword": _keyword_name(index), "device": device,
                        **_metric(impression, click, click * (6.4 + index % 5)),
                        "raw_metrics": {"fixture": FIXTURE_KEY, "synthetic": True},
                        "fetched_at": _iso_stamp(end_date), "fixture_key": FIXTURE_KEY,
                    })

    search_terms = []
    for index in range(48):
        account, campaign, adgroup, keyword = _ids(index % 24)
        impression = 30 + index * 3
        click = 1 + index % 8
        search_terms.append({
            "tenant_id": TENANT_ID, "baidu_account_id": account,
            "query_word": f"虚拟搜索词 {index + 1:02d}",
            "trigger_keyword": _keyword_name(index % 24), "query_status": index % 3,
            "campaign_id": campaign, "adgroup_id": adgroup, "match_id": index % 4,
            **_metric(impression, click, click * (5.9 + index % 6)),
            "conversions": 1 if index % 11 == 0 else 0,
            "window_start": start_date.isoformat(), "window_end": end_date.isoformat(),
            "is_added": index % 3 == 0, "synced_at": _iso_stamp(end_date),
            "fixture_key": FIXTURE_KEY,
        })

    alerts = [
        {"rule_code": "DEMO_DROP", "priority": "P1", "title": "近 7 天点击突然下滑", "scenario": "sudden_drop", "keyword_index": 6},
        {"rule_code": "DEMO_BUDGET", "priority": "P1", "title": "计划预算接近上限", "scenario": "budget_pressure", "keyword_index": 0},
        {"rule_code": "DEMO_MISSING", "priority": "P2", "title": "关键词报告存在缺报", "scenario": "missing_report", "keyword_index": 20},
        {"rule_code": "DEMO_ZERO", "priority": "P3", "title": "关键词出现真实零值", "scenario": "observed_zero", "keyword_index": 19},
        {"rule_code": "DEMO_PHONE", "priority": "P3", "title": "电话按钮点击仅部分可用", "scenario": "partial_phone", "keyword_index": 8},
        {"rule_code": "DEMO_QUALITY", "priority": "P4", "title": "部分关键词质量度偏低", "scenario": "quality", "keyword_index": 2},
    ]
    for alert_index, row in enumerate(alerts):
        _, campaign, _, keyword = _ids(row.pop("keyword_index"))
        row.update({
            "tenant_id": TENANT_ID, "keyword_id": keyword, "campaign_id": campaign,
            "message": "【全虚拟演示】用于展示告警处理流程，不代表真实投放结果。",
            "report_date": (end_date - timedelta(days=alert_index)).isoformat(),
            "status": "resolved" if alert_index == 5 else "open",
            "metrics": {"fixture": FIXTURE_KEY, "synthetic": True, "scenario": row["scenario"]},
            "fixture_key": FIXTURE_KEY,
        })

    tasks = []
    task_targets = (
        {"metric_key": "sem.accounts.active_count", "direction": "up", "target_value": 1},
        {"metric_key": "sem.approvals.pending_count", "direction": "down", "target_value": 0},
        {"metric_key": "sem.identity.conflict_tenant_count", "direction": "down", "target_value": 0},
        {"metric_key": "sem.approvals.pending_count", "direction": "down", "target_value": 0},
        {"metric_key": "sem.identity.conflict_tenant_count", "direction": "down", "target_value": 0},
    )
    for index, title in enumerate(("核对点击下滑", "复查预算节奏", "确认缺报范围", "整理搜索词机会", "复核电话点击口径")):
        tasks.append({
            "tenant_id": TENANT_ID, "module": "sem", "action_type": "metric_target",
            "title": f"【虚拟演示】{title}", "status": ("open", "in_progress", "done", "open", "done")[index],
            "created_by": "sem-demo-generator", "assignee_role": "operator", "params": task_targets[index],
            "baseline_snapshot": {"synthetic": True, "fixture_key": FIXTURE_KEY, "period_end": end_date.isoformat()},
            "completion_evidence": ({"synthetic": True, "result": "演示已完成"} if index in {2, 4} else None),
            "created_at": _iso_stamp(end_date - timedelta(days=5 - index)),
            "updated_at": _iso_stamp(end_date - timedelta(days=4 - index)),
            "fixture_key": FIXTURE_KEY,
        })

    operations = []
    for index in range(8):
        _, campaign, adgroup, keyword = _ids(index)
        operations.append({
            "tenant_id": TENANT_ID, "baidu_account_id": ACCOUNT_IDS[index // 4],
            "opt_time": _iso_stamp(end_date - timedelta(days=index), 8),
            "opt_type": 4, "opt_level": 5, "opt_content": "bidPriceWord",
            "opt_obj": _keyword_name(index), "old_value": f"{5.0 + index / 10:.2f}",
            "new_value": f"{5.2 + index / 10:.2f}", "plan_id": campaign, "unit_id": adgroup,
            "dedup_key": hashlib.md5(f"{FIXTURE_KEY}:operation:{keyword}".encode()).hexdigest(),
            "synced_at": _iso_stamp(end_date), "fixture_key": FIXTURE_KEY,
            "synthetic_note": "虚拟历史记录；未调用百度写接口",
        })

    tables = {
        "tenants": [{"id": TENANT_ID, "tenant_id": TENANT_ID, "name": "G-Snipers 全域演示",
                     "baidu_ucid": None, "strategy": "demo", "monthly_budget": 100_000,
                     "business_desc": "【全虚拟演示】不对应任何真实客户、账户或投放。",
                     "fixture_key": FIXTURE_KEY}],
        "tenant_modules": [{"tenant_id": TENANT_ID, "module_code": "sem", "status": "active",
                            "module_settings": {"fixture_key": FIXTURE_KEY, "data_mode": "demo"},
                            "fixture_key": FIXTURE_KEY}],
        "baidu_accounts": [
            {"id": account, "tenant_id": TENANT_ID, "baidu_username": f"demo-disabled-{offset + 1}",
             "baidu_ucid": 990_900_001 + offset, "status": "disabled", "auth_mode": "demo",
             "sync_status": "disabled", "scheduler_eligible": False, "writeback_allowed": False,
             "credentials": None, "fixture_key": FIXTURE_KEY}
            for offset, account in enumerate(ACCOUNT_IDS)
        ],
        "campaigns": campaigns, "adgroups": adgroups, "keywords": keywords,
        "kw_report_snapshots": snapshots, "keyword_region_reports": region_reports,
        "keyword_hourly_reports": hourly_reports, "search_term_reports": search_terms,
        "alerts": alerts, "sem_tasks": tasks, "operation_records": operations,
    }
    for table_name, base_id in TABLE_ID_BASES.items():
        for index, row in enumerate(tables[table_name]):
            row.setdefault("id", base_id + index)
    bundle = {
        "manifest": {
            "fixture_key": FIXTURE_KEY, "schema_version": 1, "synthetic": True,
            "tenant": {"id": TENANT_ID, "name": "G-Snipers 全域演示", "protected_real_tenant_ids": sorted(PROTECTED_TENANT_IDS)},
            "window": {"start": start_date.isoformat(), "end": end_date.isoformat(), "days": 90, "timezone": "Asia/Shanghai"},
            "safety": {"database_writes": False, "network_calls": False, "baidu_sync": False,
                       "writeback": False, "all_external_accounts_disabled_demo": True},
            "scenarios": ["normal_growth", "sudden_drop", "budget_pressure", "missing_report", "observed_zero", "phone_known", "phone_partial", "phone_unavailable", "phone_no_data"],
            "phone_semantics": "电话按钮点击不等于拨通电话或有效咨询；部分覆盖只显示已知小计。",
            "source_scope": "关键词报告花费，不代表全部广告产品账户消耗。",
            "idempotency": {"strategy": "stable reserved IDs plus fixture_key", "replace_scope": {"tenant_id": TENANT_ID, "fixture_key": FIXTURE_KEY}},
            "cleanup": {"mode": "review-only", "required_match": {"tenant_id": TENANT_ID, "fixture_key": FIXTURE_KEY},
                        "delete_order": ["sem_tasks", "alerts", "operation_records", "search_term_reports", "keyword_hourly_reports", "keyword_region_reports", "kw_report_snapshots", "keywords", "adgroups", "campaigns", "baidu_accounts", "tenant_modules", "tenants"]},
        },
        "tables": tables,
    }
    bundle["manifest"]["counts"] = {name: len(rows) for name, rows in tables.items()}
    validate_bundle(bundle)
    return bundle


def validate_bundle(bundle: dict[str, Any]) -> None:
    manifest = bundle["manifest"]
    tables = bundle["tables"]
    if manifest["tenant"]["id"] in PROTECTED_TENANT_IDS:
        raise ValueError("demo tenant collides with a protected real tenant")
    execution_flags = ("database_writes", "network_calls", "baidu_sync", "writeback")
    if (not manifest["synthetic"]
            or any(manifest["safety"][key] for key in execution_flags)
            or not manifest["safety"]["all_external_accounts_disabled_demo"]):
        raise ValueError("demo safety flags must remain fail-closed")
    for account in tables["baidu_accounts"]:
        if account["status"] != "disabled" or account["auth_mode"] != "demo":
            raise ValueError("demo accounts must remain disabled/demo")
        if account["scheduler_eligible"] or account["writeback_allowed"] or account["credentials"] is not None:
            raise ValueError("demo accounts cannot carry execution capability")
    for name, rows in tables.items():
        ids = [row["id"] for row in rows]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate internal ID in {name}")
        for row in rows:
            if row.get("tenant_id") != TENANT_ID:
                raise ValueError(f"cross-tenant row in {name}")
            if row.get("fixture_key") != FIXTURE_KEY:
                raise ValueError(f"unowned row in {name}")
    if not any(row["impression"] == row["click"] == 0 and row["cost"] == 0 for row in tables["kw_report_snapshots"]):
        raise ValueError("fixture must include an observed zero row")


def canonical_bytes(bundle: dict[str, Any]) -> bytes:
    return (json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def write_bundle(bundle: dict[str, Any], output: Path) -> str:
    payload = canonical_bytes(bundle)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, output)
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end-date", type=date.fromisoformat, default=DEFAULT_END_DATE)
    parser.add_argument("--output", type=Path, help="write inert JSON; no database option exists")
    args = parser.parse_args()
    bundle = build_bundle(args.end_date)
    digest = hashlib.sha256(canonical_bytes(bundle)).hexdigest()
    if args.output:
        digest = write_bundle(bundle, args.output)
    print(json.dumps({"fixture_key": FIXTURE_KEY, "tenant_id": TENANT_ID,
                      "window": bundle["manifest"]["window"], "counts": bundle["manifest"]["counts"],
                      "sha256": digest, "output": str(args.output) if args.output else None},
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
