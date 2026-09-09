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
    (160100001, 160001, "工业泵选型", 160201, 160301, 8.60, False),
    (160100002, 160001, "耐腐蚀离心泵", 160201, 160301, 11.20, False),
    (160100003, 160001, "化工泵厂家", 160202, 160302, 7.90, False),
    (160100004, 160002, "污水提升泵", 160203, 160303, 6.50, False),
    (160100005, 160002, "高扬程水泵", 160203, 160303, 9.30, True),
    (160100006, 160002, "泵站改造方案", 160204, 160304, None, False),
)

_SEARCH_TERMS = (
    (160400001, 160001, "工业泵怎么选型", "工业泵选型", 160201, 160301, 18.40, 5, 236),
    (160400002, 160001, "耐腐蚀离心泵报价", "耐腐蚀离心泵", 160201, 160301, 26.20, 7, 318),
    (160400003, 160001, "化工泵生产厂家", "化工泵厂家", 160202, 160302, 15.80, 4, 205),
    (160400004, 160002, "污水提升泵参数", "污水提升泵", 160203, 160303, 12.10, 3, 184),
    (160400005, 160002, "高扬程水泵价格", "高扬程水泵", 160203, 160303, 9.60, 2, 141),
    (160400006, 160002, "泵站节能改造", "泵站改造方案", 160204, 160304, 7.30, 1, 92),
)


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
