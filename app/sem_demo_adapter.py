"""Tenant-scoped, embedded SEM demo reads for the workbench demo identity.

The adapter is deterministic and side-effect free.  It does not use the database,
Baidu clients, task queues, AI services, caches, or writeback code.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from app.security.auth import AuthContext
from app.sem_cockpit_readonly import validate_window

DEMO_TENANT_ID = 16
DEMO_USERNAME = "workbench_test_readonly"
DEMO_REVISION = "sem-demo-tenant16-v1"
DEMO_ACCOUNTS = (160001, 160002)
DEMO_DEFAULT_END = date(2026, 9, 10)

_KEYWORDS = (
    (160100001, 160001, "TIGER粉末涂料", 160201, 160301, 8.60, False),
    (160100002, 160001, "TIGER低温固化粉末", 160201, 160301, 11.20, False),
    (160100003, 160001, "粉末涂料生产厂家", 160202, 160302, 7.90, False),
    (160100004, 160002, "金属表面粉末喷涂", 160203, 160303, 6.50, False),
    (160100005, 160002, "户外耐候粉末涂料", 160203, 160303, 9.30, True),
    (160100006, 160002, "表面涂装升级方案", 160204, 160304, None, False),
)

_SEARCH_TERMS = (
    (160400001, 160001, "粉末涂料怎么选", "TIGER粉末涂料", 160201, 160301, 18.40, 5, 236),
    (160400002, 160001, "低温固化粉末报价", "TIGER低温固化粉末", 160201, 160301, 26.20, 7, 318),
    (160400003, 160001, "粉末涂料生产厂家", "粉末涂料生产厂家", 160202, 160302, 15.80, 4, 205),
    (160400004, 160002, "金属表面粉末喷涂工艺", "金属表面粉末喷涂", 160203, 160303, 12.10, 3, 184),
    (160400005, 160002, "户外耐候粉末涂料价格", "户外耐候粉末涂料", 160203, 160303, 9.60, 2, 141),
    (160400006, 160002, "表面涂装线升级", "表面涂装升级方案", 160204, 160304, 7.30, 1, 92),
)

_ACCOUNT_NAMES = {
    160001: "TIGER品牌推广（演示）",
    160002: "TIGER行业推广（演示）",
}


def is_demo_read(ctx: AuthContext, tenant_id: int) -> bool:
    """Require both the existing login identity and its bound demo tenant."""
    return (
        tenant_id == DEMO_TENANT_ID
        and ctx.username == DEMO_USERNAME
        and ctx.tenant_id == DEMO_TENANT_ID
        and not ctx.is_superadmin
    )


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _metrics(cost: float | None, click: int | None, impression: int | None) -> dict[str, Any]:
    normalized_cost = round(cost, 2) if cost is not None else None
    return {
        "cost": normalized_cost,
        "click": click,
        "impression": impression,
        "ctr": round(click / impression, 6) if click is not None and impression else None,
        "cpc": round(normalized_cost / click, 2) if normalized_cost is not None and click else None,
    }


def _sum(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return _metrics(None, None, None)
    return _metrics(
        sum(row["cost"] for row in rows),
        sum(row["click"] for row in rows),
        sum(row["impression"] for row in rows),
    )


def _days(start: date, end: date) -> list[date]:
    validate_window(start, end)
    return [start + timedelta(days=index) for index in range((end - start).days + 1)]


def _account_scope(account_id: int | None, observed: list[int] | None = None) -> dict[str, Any]:
    if account_id is not None and account_id not in DEMO_ACCOUNTS:
        raise HTTPException(404, "该演示客户下不存在此账户")
    selected = [account_id] if account_id is not None else list(DEMO_ACCOUNTS)
    return {
        "mode": "single" if account_id is not None else "all",
        "baidu_account_id": account_id,
        "configured_account_ids": selected,
        "observed_account_ids": observed if observed is not None else selected,
        "excluded_archived_account_ids": [],
        "excluded_non_active_account_ids": [],
        **({"selected_account_status": "demo"} if account_id is not None else {}),
    }


def _envelope(source: str, account_scope: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": "sem-cockpit-v1",
        "demo_revision": DEMO_REVISION,
        "module": "sem",
        "tenant_id": DEMO_TENANT_ID,
        "is_demo": True,
        "read_only": True,
        "source": source,
        "account_scope": account_scope,
        "retrieved_at": _stamp(),
        "units": {"cost": "CNY", "click": "count", "impression": "count", "ctr": "ratio", "cpc": "CNY/click"},
        "demo_policy": {
            "data_origin": "embedded_synthetic_fixture",
            "external_calls": False,
            "persistent_writes": False,
            "actions": "simulation_only",
        },
    }


def _observed(day: date) -> bool:
    # Sundays demonstrate a missing report; Mondays are observed true-zero days.
    return day.weekday() != 6


def _daily_account(day: date, account_id: int, device: int) -> dict[str, Any] | None:
    if not _observed(day):
        return None
    if day.weekday() == 0:
        return {"cost": 0.0, "click": 0, "impression": 0}
    account_index = DEMO_ACCOUNTS.index(account_id)
    if device == 0:
        return {"cost": 18.0 + account_index * 6 + day.day * 0.7,
                "click": 4 + account_index + day.day % 3,
                "impression": 210 + account_index * 55 + day.day * 4}
    return {"cost": 27.0 + account_index * 8 + day.day * 0.9,
            "click": 6 + account_index + day.day % 4,
            "impression": 330 + account_index * 70 + day.day * 6}


def _coverage(days: list[date], rows: list[dict[str, Any]], updated_at: str) -> dict[str, Any]:
    seen = sorted({row["date"] for row in rows})
    return {
        "status": "observed" if rows else "no_data",
        "completeness": "unknown",
        "observed_days": len(seen),
        "missing_dates": [day.isoformat() for day in days if day not in seen],
        "latest_report_date": seen[-1].isoformat() if seen else None,
        "updated_at": updated_at if rows else None,
    }


def read_demo_report(start: date, end: date, account_id: int | None) -> dict[str, Any]:
    days = _days(start, end)
    selected = [account_id] if account_id is not None else list(DEMO_ACCOUNTS)
    _account_scope(account_id)
    rows = []
    for day in days:
        for aid in selected:
            for device in (0, 1):
                value = _daily_account(day, aid, device)
                if value is not None:
                    rows.append({"date": day, "account": aid, "device": device, **value})
    updated_at = "2026-09-10T00:35:00+00:00"
    scope = _account_scope(account_id, sorted({row["account"] for row in rows}))
    scope["includes_unassigned"] = False
    payload = {
        **_envelope("kw_report_snapshots", scope),
        "source_scope": "keyword_report_only",
        "window": {"start": start.isoformat(), "end": end.isoformat(), "timezone": "Asia/Shanghai", "inclusive": True},
        "coverage": _coverage(days, rows, updated_at),
        "metrics": _sum(rows),
        "accounts": [],
        "trend": [],
        "devices": [],
        "unavailable": {
            "phone_button_clicks": "演示源没有可核验的电话按钮点击原始字段；不得推算为拨通电话或有效咨询。",
            "valid_consultations": "演示源没有已核实的有效咨询口径。",
            "account_balance": "只读演示不调用实时账户 API。",
        },
    }
    for aid in selected:
        account_rows = [row for row in rows if row["account"] == aid]
        payload["accounts"].append({"baidu_account_id": aid, "status": "demo",
                                    "metrics": _sum(account_rows),
                                    "coverage": _coverage(days, account_rows, updated_at)})
    for day in days:
        day_rows = [row for row in rows if row["date"] == day]
        payload["trend"].append({"date": day.isoformat(),
                                 "status": "observed" if day_rows else "no_data",
                                 **_sum(day_rows)})
    for device, label in ((0, "PC"), (1, "移动")):
        device_rows = [row for row in rows if row["device"] == device]
        if device_rows:
            payload["devices"].append({"device": device, "label": label, **_sum(device_rows)})
    return payload


def _keyword_rows(keyword: tuple, days: list[date]) -> list[dict[str, Any]]:
    keyword_id, account_id, *_ = keyword
    index = next(i for i, item in enumerate(_KEYWORDS) if item[0] == keyword_id)
    if keyword_id == 160100006:
        return []
    rows = []
    for day in days:
        if not _observed(day):
            continue
        if day.weekday() == 0:
            rows.append({"date": day, "cost": 0.0, "click": 0, "impression": 0})
        else:
            rows.append({"date": day, "cost": 6.0 + index * 2.3 + day.day * 0.25,
                         "click": 2 + index % 4, "impression": 95 + index * 27 + day.day * 3})
    return rows


def _phone_unavailable(row_count: int) -> dict[str, Any]:
    return {"value": None, "known_subtotal": None, "unit": "count",
            "source_field": "ocpcConversionsDetail2",
            "status": "unavailable" if row_count else "no_data",
            "stored_rows": row_count, "known_rows": 0, "unknown_rows": row_count,
            "completeness": "unknown"}


def _window(start: date, end: date, mode: str = "explicit") -> dict[str, Any]:
    return {"start": start.isoformat(), "end": end.isoformat(), "timezone": "Asia/Shanghai",
            "inclusive": True, "mode": mode}


def read_demo_keywords(account_id: int | None, start: date | None, end: date | None,
                       q: str | None, campaign_id: int | None, page: int, page_size: int) -> dict[str, Any]:
    if (start is None) != (end is None):
        raise HTTPException(422, "起止日期须同时提供或同时省略")
    mode = "explicit" if start else "latest_report_7d"
    end = end or DEMO_DEFAULT_END
    start = start or end - timedelta(days=6)
    days = _days(start, end)
    _account_scope(account_id)
    assets = [item for item in _KEYWORDS if account_id is None or item[1] == account_id]
    if q:
        assets = [item for item in assets if q.casefold() in item[2].casefold()]
    if campaign_id is not None:
        assets = [item for item in assets if item[3] == campaign_id]
    total = len(assets)
    assets = assets[(page - 1) * page_size: page * page_size]
    items = []
    for asset in assets:
        keyword_id, aid, word, campaign, adgroup, price, pause = asset
        rows = _keyword_rows(asset, days)
        matched = bool(rows)
        items.append({
            "keyword_id": keyword_id, "baidu_account_id": aid, "keyword": word,
            "campaign_id": campaign, "adgroup_id": adgroup, "price": price, "pause": pause,
            "asset_updated_at": "2026-09-09T23:50:00+00:00", "metrics": _sum(rows),
            "coverage": _coverage(days, rows, "2026-09-10T00:35:00+00:00"),
            "report_association": {"status": "matched" if matched else "no_report",
                "evidence_status": "matched" if matched else "no_report",
                "join_keys": ["baidu_account_id", "keyword_id"],
                "matched_report_groups": len(rows), "other_observed_account_ids": [],
                "observed_known_account_ids": [], "has_unassigned_reports": False,
                "completeness": "unknown"},
            "phone_button_clicks": _phone_unavailable(len(rows)),
        })
    counts = {"matched": sum(i["report_association"]["status"] == "matched" for i in items),
              "account_mismatch": 0,
              "no_report": sum(i["report_association"]["status"] == "no_report" for i in items)}
    evidence = {**counts, "ownership_unknown": 0, "report_ownership_unknown": 0}
    observed = sorted({item["baidu_account_id"] for item in items})
    return {**_envelope("keywords+kw_report_snapshots", _account_scope(account_id, observed)),
            "window": _window(start, end, mode), "filters": {"q": q, "campaign_id": campaign_id},
            "page": page, "page_size": page_size, "total": total, "items": items,
            "association_summary": {"scope": "current_page", "counts": counts,
                                    "evidence_counts": evidence, "completeness": "unknown"},
            "scope_note": "内置演示关键词；指标只按相同演示账户与关键词 ID 关联。"}


def _dimension_coverage(days: list[date], has_rows: bool, stamp: str) -> dict[str, Any]:
    observed_days = [day for day in days if _observed(day)] if has_rows else []
    rows = [{"date": day} for day in observed_days]
    return _coverage(days, rows, stamp)


def read_demo_keyword_detail(keyword_id: int, account_id: int | None,
                             start: date, end: date) -> dict[str, Any]:
    days = _days(start, end)
    _account_scope(account_id)
    matches = [item for item in _KEYWORDS if item[0] == keyword_id and (account_id is None or item[1] == account_id)]
    if not matches:
        raise HTTPException(404, "该演示范围不存在此关键词")
    asset = matches[0]
    rows = _keyword_rows(asset, days)
    aid = asset[1]
    payload = read_demo_report(start, end, aid)
    payload["account_scope"] = _account_scope(account_id, [aid])
    payload["account_scope"]["includes_unassigned"] = False
    payload["metrics"] = _sum(rows)
    payload["coverage"] = _coverage(days, rows, "2026-09-10T00:35:00+00:00")
    payload["accounts"] = [{"baidu_account_id": aid, "status": "demo", "metrics": _sum(rows),
                            "coverage": payload["coverage"],
                            "phone_button_clicks": _phone_unavailable(len(rows))}]
    payload["trend"] = [{"date": day.isoformat(),
                         "status": "observed" if any(row["date"] == day for row in rows) else "no_data",
                         **_sum([row for row in rows if row["date"] == day])} for day in days]
    payload["devices"] = [{"device": 0, "label": "PC", **_metrics(
        round(payload["metrics"]["cost"] * 0.42, 2) if rows else None,
        round(payload["metrics"]["click"] * 0.4) if rows else None,
        round(payload["metrics"]["impression"] * 0.38) if rows else None)},
        {"device": 1, "label": "移动", **_metrics(
        round(payload["metrics"]["cost"] * 0.58, 2) if rows else None,
        payload["metrics"]["click"] - round(payload["metrics"]["click"] * 0.4) if rows else None,
        payload["metrics"]["impression"] - round(payload["metrics"]["impression"] * 0.38) if rows else None)}] if rows else []
    payload["phone_button_clicks"] = _phone_unavailable(len(rows))
    payload["unavailable"]["phone_button_clicks"] = "演示源没有可核验的电话按钮点击原始字段。"
    payload["keyword_id"] = keyword_id
    payload["keyword_assets"] = [{"baidu_account_id": aid, "keyword": asset[2],
                                  "asset_updated_at": "2026-09-09T23:50:00+00:00"}]
    region_rows = [
        {"region_level": "province", "region_name": "华东演示区", "metrics": _metrics(48.6, 12, 620)},
        {"region_level": "province", "region_name": "华南演示区", "metrics": _metrics(31.4, 8, 455)},
        {"region_level": "city", "region_name": "示例市 A", "metrics": _metrics(22.8, 6, 310)},
        {"region_level": "city", "region_name": "示例市 B", "metrics": _metrics(16.2, 4, 240)},
    ] if rows else []
    dim_stamp = "2026-09-10T00:20:00+00:00"
    dim_coverage = _dimension_coverage(days, bool(rows), dim_stamp)
    cells = []
    for weekday in range(1, 8):
        for hour in range(24):
            observed = bool(rows) and weekday in (2, 3, 4, 5) and hour in (9, 10, 14, 15, 16)
            cell_metrics = _metrics(3.2 + weekday + hour / 10, 1 + hour % 3, 38 + weekday * 4 + hour) if observed else _metrics(None, None, None)
            cells.append({"weekday": weekday, "hour": hour,
                          "status": "observed" if observed else "no_data",
                          "metrics": cell_metrics})
    observed_cells = [cell for cell in cells if cell["status"] == "observed"]
    payload["dimensions"] = {
        "region": {"source": "keyword_region_reports", "window": _window(start, end),
                   "coverage": dim_coverage,
                   "accounts": [{"baidu_account_id": aid, "coverage": dim_coverage}],
                   "rows": region_rows,
                   "totals_by_level": [{"region_level": level,
                       "metrics": _sum([row["metrics"] for row in region_rows if row["region_level"] == level])}
                       for level in ("city", "province") if region_rows],
                   "scope_note": "演示地域按省级和城市级分别展示，不跨层级相加。"},
        "schedule": {"source": "keyword_hourly_reports", "window": _window(start, end),
                     "coverage": dim_coverage,
                     "accounts": [{"baidu_account_id": aid, "coverage": dim_coverage}],
                     "dimension": "weekday_hour", "cells": cells,
                     "metrics": _sum([cell["metrics"] for cell in observed_cells])},
    }
    return payload


def read_demo_search_terms(account_id: int | None, q: str | None,
                           campaign_id: int | None, adgroup_id: int | None,
                           page: int, page_size: int) -> dict[str, Any]:
    _account_scope(account_id)
    rows = [item for item in _SEARCH_TERMS if account_id is None or item[1] == account_id]
    if q:
        rows = [item for item in rows if q.casefold() in item[2].casefold()]
    if campaign_id is not None:
        rows = [item for item in rows if item[4] == campaign_id]
    if adgroup_id is not None:
        rows = [item for item in rows if item[5] == adgroup_id]
    total = len(rows)
    window_start, window_end = date(2026, 9, 4), date(2026, 9, 10)
    stamp = "2026-09-10T00:40:00+00:00"
    account_counts = {aid: sum(item[1] == aid for item in rows) for aid in DEMO_ACCOUNTS}
    observed = [aid for aid, count in account_counts.items() if count]
    windows = [{"baidu_account_id": aid, **_window(window_start, window_end, "sync_snapshot"),
                "stored_rows": count, "updated_at": stamp, "oldest_updated_at": stamp,
                "unknown_timestamp_rows": 0, "completeness": "unknown"}
               for aid, count in account_counts.items() if count]
    page_rows = rows[(page - 1) * page_size: page * page_size]
    return {**_envelope("search_term_reports", _account_scope(account_id, observed)),
            "filters": {"q": q, "campaign_id": campaign_id, "adgroup_id": adgroup_id},
            "windows": windows, "mixed_windows": False,
            "status": "observed" if total else "no_data", "completeness": "unknown",
            "page": page, "page_size": page_size, "total": total,
            "items": [{"id": item[0], "baidu_account_id": item[1], "query_word": item[2],
                       "trigger_keyword": item[3], "campaign_id": item[4], "adgroup_id": item[5],
                       "metrics": _metrics(item[6], item[7], item[8]),
                       "window": _window(window_start, window_end, "sync_snapshot"),
                       "updated_at": stamp} for item in page_rows],
            "scope_note": "内置演示搜索词使用固定同步窗口；触发词文本不是点击级归因，不返回跨窗口总量。"}


def _demo_meta() -> dict[str, Any]:
    return {
        "is_demo": True, "read_only": True, "demo_revision": DEMO_REVISION,
        "demo_policy": {"data_origin": "embedded_synthetic_fixture", "external_calls": False,
                        "persistent_writes": False, "actions": "disabled"},
    }


def read_demo_account_budget(account_id: int | None) -> dict[str, Any]:
    _account_scope(account_id)
    if account_id is None:
        raise HTTPException(409, "当前演示客户有多个推广账户，请先选择账户")
    index = DEMO_ACCOUNTS.index(account_id)
    return {**_demo_meta(), "status": "ok", "baidu_account_id": account_id,
            "baidu_account_name": _ACCOUNT_NAMES[account_id], "budget": 600.0 + index * 200,
            "budget_type": 1, "has_daily_budget": True, "balance": 3200.0 + index * 900,
            "cost": 186.4 + index * 42.8, "min_budget": 50, "max_budget": 10_000_000,
            "updated_at": "2026-09-10T00:45:00+00:00",
            "scope_note": "内置演示快照；未访问百度实时账户接口。"}


def read_demo_campaigns(account_id: int | None) -> dict[str, Any]:
    _account_scope(account_id)
    rows = []
    for index, (campaign_id, name) in enumerate(_CAMPAIGN_NAMES.items()):
        aid = DEMO_ACCOUNTS[0 if index < 2 else 1]
        if account_id is not None and aid != account_id:
            continue
        rows.append({"campaign_id": campaign_id, "campaign_name": name,
                     "baidu_account_id": aid, "baidu_account_name": _ACCOUNT_NAMES[aid],
                     "budget": 220.0 + index * 60, "pause": index == 3, "status": 23 if index == 3 else 21,
                     "region_target": [1000 + index], "region_price_factor": [], "geo_location_status": 0,
                     "schedule_price_factors": [{"timeId": day * 100 + hour, "priceFactor": 1.0}
                                                for day in range(1, 6) for hour in range(9, 18)],
                     "synced_at": "2026-09-10T00:42:00+00:00"})
    return {**_demo_meta(), "total": len(rows), "campaigns": rows,
            "accounts": [{"id": aid, "name": _ACCOUNT_NAMES[aid], "status": "active"}
                         for aid in DEMO_ACCOUNTS], "min_budget": 50, "max_budget": 10_000_000}


def read_demo_adgroups(campaign_id: int | None) -> dict[str, Any]:
    rows = []
    for index, (adgroup_id, name) in enumerate(_ADGROUP_NAMES.items()):
        campaign = list(_CAMPAIGN_NAMES)[index]
        if campaign_id is not None and campaign != campaign_id:
            continue
        rows.append({"adgroup_id": adgroup_id, "adgroup_name": name, "campaign_id": campaign,
                     "campaign_name": _CAMPAIGN_NAMES[campaign], "max_price": 7.2 + index * 1.1,
                     "pause": index == 3, "status": 23 if index == 3 else 21,
                     "pc_final_url": f"https://demo.invalid/landing/{adgroup_id}",
                     "mobile_final_url": f"https://demo.invalid/landing/{adgroup_id}",
                     "pc_track_param": None, "mobile_track_param": None,
                     "pc_track_template": None, "mobile_track_template": None})
    return {**_demo_meta(), "total": len(rows), "adgroups": rows,
            "sync": {"accounts": 2, "active_accounts": 2, "status": "demo",
                     "last_synced_at": "2026-09-10T00:42:00+00:00", "error": None}}


_DEMO_ALERTS = (
    {"id": 160500001, "priority": "P1", "title": "点击成本上升", "message": "TIGER粉末涂料关键词近日报告成本上升，请结合品牌推广目标复核。",
     "report_date": "2026-09-10", "keyword_id": 160100001, "keyword": "TIGER粉末涂料", "campaign_id": 160201,
     "campaign_name": "TIGER品牌推广", "metrics": {"成本": 38.6, "点击": 7}, "status": "open", "source": "rule",
     "detected_at": "2026-09-10T00:50:00", "resolved_at": None, "streak": {"days": 2, "first_date": "2026-09-09"}},
    {"id": 160500002, "priority": "P3", "title": "展现下降", "message": "表面技术推广计划展现较前一观察窗口下降。",
     "report_date": "2026-09-09", "keyword_id": 160100004, "keyword": "金属表面粉末喷涂", "campaign_id": 160203,
     "campaign_name": "表面技术解决方案", "metrics": {"展现": 184}, "status": "resolved", "source": "rule",
     "detected_at": "2026-09-09T00:50:00", "resolved_at": "2026-09-09T03:10:00"},
)


def read_demo_alerts(status: str | None, priority: str | None, campaign_id: int | None,
                     alert_type: str | None, limit: int) -> dict[str, Any]:
    rows = list(_DEMO_ALERTS)
    if status and status != "all": rows = [row for row in rows if row["status"] == status]
    if priority: rows = [row for row in rows if row["priority"] == priority]
    if campaign_id is not None: rows = [row for row in rows if row["campaign_id"] == campaign_id]
    if alert_type: rows = [row for row in rows if row["title"] == alert_type]
    counts = {f"P{i}": 0 for i in range(6)}
    for row in _DEMO_ALERTS:
        if row["status"] == "open": counts[row["priority"]] += 1
    return {**_demo_meta(), "open_counts": counts, "total_open": sum(counts.values()), "today_new": 1,
            "group_options": {"campaigns": [{"id": cid, "name": name} for cid, name in _CAMPAIGN_NAMES.items()],
                              "types": sorted({row["title"] for row in _DEMO_ALERTS})}, "alerts": rows[:limit],
            "updated_at": "2026-09-10T00:50:00+00:00"}


def read_demo_operations(opt_level: int | None, opt_content: str | None, q: str | None,
                         start_date: date | None, end_date: date | None, over_limit: bool | None,
                         page: int, page_size: int) -> dict[str, Any]:
    records = [
        {"id": 160600001, "opt_time": "2026-09-10T09:20:00", "opt_level": 5, "level_label": "关键词",
         "opt_type": 4, "type_label": "修改", "opt_content": "bidPriceWord", "content_label": "关键词出价",
         "opt_obj": "TIGER粉末涂料", "keyword_id": 160100001, "campaign_name": "TIGER品牌推广", "adgroup_name": "产品与报价",
         "old_value": "8.00", "new_value": "8.60", "change": {"pct": 7.5, "over_limit": False}, "source": "演示快照",
         "ai_suggestion": None, "adopted": None, "effect_review": None},
        {"id": 160600002, "opt_time": "2026-09-08T15:10:00", "opt_level": 2, "level_label": "计划",
         "opt_type": 4, "type_label": "修改", "opt_content": "budget", "content_label": "计划预算",
         "opt_obj": "涂装升级专项", "keyword_id": None, "campaign_name": "涂装升级专项", "adgroup_name": None,
         "old_value": "200", "new_value": "260", "change": {"pct": 30.0, "over_limit": True}, "source": "演示快照",
         "ai_suggestion": None, "adopted": None, "effect_review": None},
    ]
    if opt_level is not None: records = [r for r in records if r["opt_level"] == opt_level]
    if opt_content: records = [r for r in records if r["opt_content"] == opt_content]
    if q: records = [r for r in records if q.casefold() in r["opt_obj"].casefold()]
    if start_date: records = [r for r in records if r["opt_time"][:10] >= start_date.isoformat()]
    if end_date: records = [r for r in records if r["opt_time"][:10] <= end_date.isoformat()]
    if over_limit: records = [r for r in records if r["change"] and r["change"]["over_limit"]]
    total = len(records)
    return {**_demo_meta(), "summary": {"month_total": 2, "month_keyword_level": 1,
            "month_coef_level": 1, "month_over_limit": 1}, "total": total, "page": page, "page_size": page_size,
            "last_synced_at": "2026-09-10T00:55:00+00:00",
            "content_options": [{"code": "bidPriceWord", "label": "关键词出价"}, {"code": "budget", "label": "计划预算"}],
            "records": records[(page - 1) * page_size:page * page_size]}


def read_demo_writebacks(status: str | None = None, limit: int = 200) -> dict[str, Any]:
    rows = [{"id": 160700001, "baidu_account_id": 160001, "keyword_id": 160100001,
             "keyword": "TIGER粉末涂料", "old_bid": 8.0, "new_bid": 8.6, "status": "dry_run", "dry_run": True,
             "error_msg": None, "operator_name": "演示用户", "created_at": "2026-09-10T01:00:00"}]
    if status and status != "all": rows = [r for r in rows if r["status"] == status]
    return {**_demo_meta(), "writebacks": rows[:limit]}


def read_demo_approvals(status: str | None = None, limit: int = 100) -> dict[str, Any]:
    rows = [{"id": 160710001, "tenant_id": 16, "action_type": "campaign_budget",
             "payload": {"campaign_id": 160201, "new_budget": 280}, "status": "consumed",
             "request_note": "演示审计记录", "decision_note": "演示数据", "requested_by": 5016,
             "approved_by": 5016, "consumed_by": 5016, "created_at": "2026-09-08T02:00:00",
             "decided_at": "2026-09-08T02:01:00", "consumed_at": "2026-09-08T02:02:00"}]
    if status and status != "all": rows = [r for r in rows if r["status"] == status]
    return {**_demo_meta(), "approvals": rows[:limit]}


def read_demo_actions(action_type: str | None = None, limit: int = 200) -> dict[str, Any]:
    rows = [{"id": 160720001, "baidu_account_id": 160001, "action_type": "negative", "action_label": "加否词",
             "word": "二手喷涂设备", "campaign_name": "TIGER品牌推广", "adgroup_name": "产品与报价",
             "status": "dry_run", "status_label": "演练", "dry_run": True, "execution_mode_label": "演练（未修改百度）",
             "operator_name": "演示用户", "created_at": "2026-09-09T03:00:00", "result_note": "演示记录"}]
    if action_type: rows = [r for r in rows if r["action_type"] == action_type]
    return {**_demo_meta(), "actions": rows[:limit]}


_CATEGORY_BY_KEYWORD = {
    160100001: "focus",
    160100002: "focus",
    160100003: "normal",
    160100004: "longtail",
    160100005: "normal",
    160100006: "new",
}
_CATEGORY_LABELS = {
    "brand": "品牌词",
    "focus": "重点词",
    "normal": "普通词",
    "longtail": "长尾词",
    "new": "新词",
}
_CAMPAIGN_NAMES = {
    160201: "TIGER品牌推广",
    160202: "工业粉末涂料获客",
    160203: "表面技术解决方案",
    160204: "涂装升级专项",
}
_ADGROUP_NAMES = {
    160301: "产品与报价",
    160302: "粉末涂料厂家",
    160303: "金属与户外应用",
    160304: "涂装工艺升级",
}


def _classic_change(current: float | int | None, previous: float | int | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return round((current - previous) / previous * 100, 1)


def _classic_compare(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    return {
        key: {
            "current": current.get(key),
            "previous": previous.get(key),
            "change_pct": _classic_change(current.get(key), previous.get(key)),
        }
        for key in ("cost", "click", "impression", "cpc", "ctr")
    }


def read_demo_dashboard_today(start: date | None, end: date | None) -> dict[str, Any]:
    """Return the classic dashboard shape without DB, Baidu, cache, or AI calls."""
    end = end or DEMO_DEFAULT_END
    start = start or end.replace(day=1)
    days = _days(start, end)
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=len(days) - 1)
    report = read_demo_report(start, end, None)
    previous = read_demo_report(previous_start, previous_end, None)
    metrics = report["metrics"]
    previous_metrics = previous["metrics"]
    device_split = []
    total_cost = metrics.get("cost") or 0
    for row in report["devices"]:
        device_split.append({
            "device": row["label"],
            "cost": row["cost"],
            "click": row["click"],
            "impression": row["impression"],
            "cpc": row["cpc"],
            "ctr": row["ctr"],
            "cost_share_pct": round(row["cost"] / total_cost * 100, 1) if total_cost else None,
        })
    campaign_weights = ((160201, 0.38), (160202, 0.22), (160203, 0.27), (160204, 0.13))
    top_campaigns = []
    for campaign_id, weight in campaign_weights:
        cost = round((metrics.get("cost") or 0) * weight, 2)
        click = round((metrics.get("click") or 0) * weight)
        impression = round((metrics.get("impression") or 0) * weight)
        top_campaigns.append({
            "campaign_id": campaign_id,
            "campaign_name": _CAMPAIGN_NAMES[campaign_id],
            **_metrics(cost, click, impression),
        })
    month_cost = metrics.get("cost") or 0
    complete = not report["coverage"]["missing_dates"]
    kpi = _classic_compare(metrics, previous_metrics)
    if not complete:
        for item in kpi.values():
            item["change_pct"] = None
    return {
        **_envelope("embedded_synthetic_fixture:classic_dashboard", _account_scope(None)),
        "tenant": {"id": DEMO_TENANT_ID, "name": "SEM 演示客户", "strategy": "只读演示"},
        "period": {"start_date": start.isoformat(), "end_date": end.isoformat(), "days": len(days)},
        "kpi": kpi,
        "lead": {"current": 0, "previous": 0, "change_pct": None},
        "cpl": {"current": None, "previous": None, "change_pct": None},
        "budget": {"monthly_budget": 5000.0, "month_cost": month_cost,
                   "usage_pct": round(month_cost / 5000 * 100, 1)},
        "alert_counts": {},
        "trend": [{"date": row["date"], "cost": row["cost"], "click": row["click"],
                   "impression": row["impression"]} for row in report["trend"]],
        "trend_7d": [{"date": row["date"], "cost": row["cost"], "click": row["click"],
                     "impression": row["impression"]} for row in report["trend"]],
        "device_split": device_split,
        "top_campaigns": top_campaigns,
        "account": {"status": "error", "message": "只读演示不调用百度实时账户接口，余额与累计消费不可用。"},
        "freshness": {"latest_report_date": report["coverage"]["latest_report_date"],
                      "last_synced_at": report["coverage"]["updated_at"],
                      "sync_interval_minutes": None, "requested_data_complete": complete,
                      "missing_dates": report["coverage"]["missing_dates"]},
        "connection": {"state": "ready", "message": "版本化演示数据已加载",
                       "active_accounts": 2, "last_account_synced_at": "2026-09-10T00:35:00+00:00",
                       "asset_counts": {"campaigns": 4, "adgroups": 4, "keywords": 6, "search_terms": 6}},
    }


def read_demo_dashboard_insight(target_date: date | None, force: bool) -> dict[str, Any]:
    """Do not invoke or pretend to invoke AI for the demo identity."""
    return {
        **_envelope("embedded_synthetic_fixture:classic_dashboard_insight", _account_scope(None)),
        "enabled": False,
        "insight_date": (target_date or DEMO_DEFAULT_END).isoformat(),
        "force_ignored": bool(force),
        "reason": "只读演示不会生成 AI 洞察或写入洞察缓存。",
    }


def read_demo_classic_keywords(
    category: str | None, campaign_id: int | None, pause: bool | None,
    serving: bool | None, q: str | None, coef_warning: str | None,
    has_suggestion: bool | None, sort_by: str, order: str, page: int, page_size: int,
) -> dict[str, Any]:
    assets = list(_KEYWORDS)
    all_category_counts = {key: 0 for key in _CATEGORY_LABELS}
    for asset in assets:
        all_category_counts[_CATEGORY_BY_KEYWORD[asset[0]]] += 1
    if category:
        assets = [row for row in assets if _CATEGORY_BY_KEYWORD[row[0]] == category]
    if campaign_id is not None:
        assets = [row for row in assets if row[3] == campaign_id]
    if pause is not None:
        assets = [row for row in assets if row[6] is pause]
    if serving is not None:
        assets = [row for row in assets if (not row[6]) is serving]
    if q:
        assets = [row for row in assets if q.casefold() in row[2].casefold()]
    if coef_warning:
        expected = "orange" if coef_warning == "orange" else "normal"
        assets = [row for row in assets if ("orange" if (row[5] or 0) >= 10 else "normal") == expected]
    if has_suggestion is True:
        assets = []
    days = _days(DEMO_DEFAULT_END - timedelta(days=6), DEMO_DEFAULT_END)

    def row_metrics(asset: tuple) -> dict[str, Any]:
        return _sum(_keyword_rows(asset, days))

    sort_keys = {
        "impression": lambda row: row_metrics(row).get("impression") or -1,
        "price": lambda row: row[5] or -1,
        "clicks_7d": lambda row: row_metrics(row).get("click") or -1,
        "cost_7d": lambda row: row_metrics(row).get("cost") or -1,
    }
    assets.sort(key=sort_keys.get(sort_by, sort_keys["impression"]), reverse=order != "asc")
    total = len(assets)
    page_assets = assets[(page - 1) * page_size: page * page_size]
    rows = []
    for index, asset in enumerate(page_assets):
        keyword_id, account_id, word, camp_id, adgroup_id, price, is_paused = asset
        metrics = row_metrics(asset)
        code = _CATEGORY_BY_KEYWORD[keyword_id]
        rows.append({
            "keyword_id": keyword_id, "baidu_account_id": account_id, "keyword": word,
            "category": {"code": code, "label": _CATEGORY_LABELS[code], "source": "demo"},
            "campaign_id": camp_id, "campaign_name": _CAMPAIGN_NAMES[camp_id],
            "adgroup_id": adgroup_id, "adgroup_name": _ADGROUP_NAMES[adgroup_id],
            "match_type": "短语匹配", "price": price,
            "effective": {"multiplier": 1.0, "price": price, "warning": "normal"},
            "pause": is_paused, "serving": {"now": not is_paused, "reason": "关键词已暂停" if is_paused else "演示投放中"},
            "quality": 7 + index % 3, "total_impression": metrics.get("impression"),
            "metrics_7d": {"click": metrics.get("click"), "cost": metrics.get("cost"),
                           "impression": metrics.get("impression"),
                           "ctr": round(metrics["ctr"] * 100, 2) if metrics.get("ctr") is not None else None,
                           "cpc": metrics.get("cpc"), "avg_rank": round(1.8 + index * 0.35, 2),
                           "conversions": None, "conv_cost": None},
            "conversions": None, "first_seen_date": "2026-08-01",
            "rank_trend": [round(2.8 - index * 0.1 - day * 0.08, 2) for day in range(7)],
        })
    return {
        **_envelope("embedded_synthetic_fixture:classic_keywords", _account_scope(None)),
        "totals": {"campaigns": 4, "adgroups": 4, "keywords": 6, "serving_now": 5,
                   "current_slot": "演示时段", "last_synced_at": "2026-09-10T00:35:00+00:00"},
        "category_counts": all_category_counts,
        "campaign_options": [{"campaign_id": key, "campaign_name": value}
                             for key, value in _CAMPAIGN_NAMES.items()],
        "metrics_window": {"start": days[0].isoformat(), "end": days[-1].isoformat()},
        "page": page, "page_size": page_size, "total": total, "keywords": rows,
    }


def read_demo_classic_search_terms(
    account_id: int | None, campaign_id: int | None, adgroup_id: int | None,
    status: str | None, has_click: bool | None, q: str | None, page: int, page_size: int,
) -> dict[str, Any]:
    source = read_demo_search_terms(account_id, q, campaign_id, adgroup_id, 1, 200)
    rows = list(source["items"])
    for index, row in enumerate(rows):
        row["is_added"] = index % 3 == 2
    if status == "added":
        rows = [row for row in rows if row["is_added"]]
    elif status == "not_added":
        rows = [row for row in rows if not row["is_added"]]
    if has_click is not None:
        rows = [row for row in rows if (row["metrics"]["click"] > 0) is has_click]
    total = len(rows)
    page_rows = rows[(page - 1) * page_size: page * page_size]
    terms = []
    for row in page_rows:
        metrics = row["metrics"]
        terms.append({
            "id": row["id"], "baidu_account_id": row["baidu_account_id"],
            "query_word": row["query_word"], "trigger_keyword": row["trigger_keyword"],
            "query_status": 0 if row["is_added"] else 1,
            "status_label": "已加成关键词" if row["is_added"] else "未加成关键词",
            "is_added": row["is_added"], "campaign_id": row["campaign_id"],
            "campaign_name": _CAMPAIGN_NAMES[row["campaign_id"]],
            "adgroup_id": row["adgroup_id"], "adgroup_name": _ADGROUP_NAMES[row["adgroup_id"]],
            "impression": metrics["impression"], "click": metrics["click"], "cost": metrics["cost"],
            "ctr": round(metrics["ctr"] * 100, 2) if metrics["ctr"] is not None else None,
            "cpc": metrics["cpc"],
        })
    all_metrics = _sum([row["metrics"] for row in rows])
    window = {"baidu_account_id": account_id, "start": "2026-09-04", "end": "2026-09-10",
              "synced_at": "2026-09-10T00:40:00+00:00", "stored_rows": total}
    return {
        **_envelope("embedded_synthetic_fixture:classic_search_terms", source["account_scope"]),
        "total": total,
        "summary": {"terms": total, "with_click": sum(row["metrics"]["click"] > 0 for row in rows),
                    "impression": all_metrics["impression"] or 0, "click": all_metrics["click"] or 0,
                    "cost": all_metrics["cost"] or 0.0},
        "windows": [window], "mixed_windows": False, "summary_comparable": True,
        "window": window, "search_terms": terms, "scope_note": "版本化内置演示搜索词；所有动作均禁用。",
    }


def read_demo_classic_keyword_detail(keyword_id: int, start: date | None, end: date | None) -> dict[str, Any]:
    end = end or DEMO_DEFAULT_END
    start = start or end - timedelta(days=6)
    detail = read_demo_keyword_detail(keyword_id, None, start, end)
    asset = next(row for row in _KEYWORDS if row[0] == keyword_id)
    metrics = detail["metrics"]
    kpi = {key: {"current": metrics.get(key), "previous": None, "change_pct": None}
           for key in ("cost", "click", "impression", "cpc", "ctr")}
    kpi.update({"avg_rank": {"current": 2.3, "previous": None, "change_pct": None},
                "conversions": {"current": None, "previous": None, "change_pct": None},
                "conv_cost": {"current": None, "previous": None, "change_pct": None}})
    region_rows = [{**row["metrics"], "region_name": row["region_name"], "region_level": row["region_level"]}
                   for row in detail["dimensions"]["region"]["rows"]]
    schedule_cells = []
    for cell in detail["dimensions"]["schedule"]["cells"]:
        value = cell["metrics"]
        schedule_cells.append({"weekday": cell["weekday"], "weekday_label": f"周{cell['weekday']}",
                               "hour": cell["hour"], "active": cell["status"] == "observed", **value})
    return {
        **_envelope("embedded_synthetic_fixture:classic_keyword_detail", _account_scope(None, [asset[1]])),
        "tenant": {"id": DEMO_TENANT_ID, "name": "SEM 演示客户"},
        "keyword": {"keyword_id": keyword_id, "keyword": asset[2],
                    "category": {"code": _CATEGORY_BY_KEYWORD[keyword_id],
                                 "label": _CATEGORY_LABELS[_CATEGORY_BY_KEYWORD[keyword_id]], "source": "demo"},
                    "pause": asset[6], "campaign_id": asset[3], "campaign_name": _CAMPAIGN_NAMES[asset[3]],
                    "adgroup_id": asset[4], "adgroup_name": _ADGROUP_NAMES[asset[4]],
                    "match_type": 17, "match_type_label": "短语匹配", "first_date": start.isoformat(),
                    "last_date": end.isoformat(), "active_days": detail["coverage"]["observed_days"]},
        "latest": {"report_date": detail["coverage"]["latest_report_date"], "bid": asset[5],
                   "quality": 8, "quality_detail": {}, "avg_rank": 2.3},
        "period": {"start_date": start.isoformat(), "end_date": end.isoformat(),
                   "days": (end - start).days + 1},
        "kpi": kpi,
        "trend": [{"date": row["date"], "cost": row["cost"], "click": row["click"],
                   "impression": row["impression"], "avg_rank": 2.3 if row["status"] == "observed" else None}
                  for row in detail["trend"]],
        "bid_trend": [{"date": start.isoformat(), "bid": asset[5]}] if asset[5] is not None else [],
        "device_split": [{"device": row["label"], "cost": row["cost"], "click": row["click"],
                          "impression": row["impression"], "cpc": row["cpc"], "ctr": row["ctr"],
                          "avg_rank": 2.3} for row in detail["devices"]],
        "region_analysis": {"source": "embedded_synthetic_fixture", "metric": "performance",
                            "summary": f"演示地域共 {len(region_rows)} 行。", "totals": _sum(region_rows),
                            "rows": region_rows},
        "schedule_analysis": {"source": "embedded_synthetic_fixture", "metric": "performance",
                              "summary": "演示星期小时数据；无数据格保持缺失。",
                              "active_hours": sum(row["active"] for row in schedule_cells), "total_hours": 168,
                              "peak_impression": max((row["impression"] or 0 for row in schedule_cells), default=0),
                              "totals": _sum([row for row in schedule_cells if row["active"]]),
                              "cells": schedule_cells},
        "alerts": [], "bid_coefficients": None,
        "search_queries": [{"query_word": row[2], "impression": row[8], "click": row[7], "cost": row[6],
                            "is_added": False, "status_label": "未加成关键词"}
                           for row in _SEARCH_TERMS if row[3] == asset[2]],
        "funnel": None, "adjustment_log": None,
    }


def read_demo_structure(kind: str, campaign_id: int | None = None) -> dict[str, Any]:
    if kind == "campaigns":
        rows = []
        for index, (campaign, name) in enumerate(_CAMPAIGN_NAMES.items()):
            rows.append({"campaign_id": campaign, "campaign_name": name, "budget": 500 + index * 150,
                         "pause": False, "status": 0, "equipment_type": 0, "price_ratio": 1.0,
                         "schedule_entries": 20, "region_entries": 2,
                         "adgroup_count": 1, "keyword_count": sum(row[3] == campaign for row in _KEYWORDS),
                         "metrics_7d": {"cost": 80 + index * 23, "click": 12 + index * 3,
                                        "impression": 820 + index * 170},
                         "leads_total": 0, "lead_cost": None, "synced_at": "2026-09-10T00:35:00+00:00"})
        return {**_envelope("embedded_synthetic_fixture:campaigns", _account_scope(None)),
                "total": len(rows), "campaigns": rows}
    rows = []
    for index, (adgroup, name) in enumerate(_ADGROUP_NAMES.items()):
        campaign = next(row[3] for row in _KEYWORDS if row[4] == adgroup)
        if campaign_id is not None and campaign != campaign_id:
            continue
        rows.append({"adgroup_id": adgroup, "adgroup_name": name, "campaign_id": campaign,
                     "campaign_name": _CAMPAIGN_NAMES[campaign], "max_price": 12 + index,
                     "pause": False, "status": 0, "price_ratio": 1.0,
                     "pc_final_url": None, "mobile_final_url": None, "pc_track_param": None,
                     "mobile_track_param": None, "pc_track_template": None, "mobile_track_template": None,
                     "negative_word_count": index, "keyword_count": sum(row[4] == adgroup for row in _KEYWORDS),
                     "metrics_7d": {"cost": 65 + index * 19, "click": 10 + index * 2,
                                    "impression": 640 + index * 150}})
    return {**_envelope("embedded_synthetic_fixture:adgroups", _account_scope(None)),
            "total": len(rows), "adgroups": rows}


def read_demo_suggestions() -> dict[str, Any]:
    return {**_envelope("embedded_synthetic_fixture:suggestions", _account_scope(None)),
            "total_pending": 0, "type_counts": {}, "suggestions": []}


def read_demo_assignees() -> dict[str, Any]:
    return {**_envelope("embedded_synthetic_fixture:assignees", _account_scope(None)), "assignees": []}


def read_demo_writeback_mode() -> dict[str, Any]:
    return {**_envelope("embedded_synthetic_fixture:writeback_mode", _account_scope(None)),
            "mode": "disabled", "writeback_enabled": False, "live_scopes": [], "accounts": []}
