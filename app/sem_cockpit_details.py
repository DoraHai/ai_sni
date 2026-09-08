"""Stored SEM evidence only. No sync, AI, cache writes or writeback imports."""
from collections import defaultdict
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import Keyword, KeywordHourlyReport, KeywordRegionReport, KwReportSnapshot, SearchTermReport
from app.sem_cockpit_readonly import (
    account_data_scope,
    phone_summary,
    read_phone_rows,
    read_report,
    report_metrics,
    resolve_account_scope,
    utc_stamp,
    validate_window,
)


async def accounts_for(session, tenant_id, account_id):
    account_scope, selected_ids, _ = await resolve_account_scope(session, tenant_id, account_id)
    return account_scope, selected_ids


def window(start, end, mode="explicit"):
    return {"start": start.isoformat() if start else None, "end": end.isoformat() if end else None,
            "timezone": "Asia/Shanghai", "inclusive": True, "mode": mode}


def coverage(rows, start, end):
    dates = {r.report_date for r in rows}
    fetched = [r.fetched_at for r in rows if r.fetched_at is not None]
    return {"status": "observed" if rows else "no_data", "completeness": "unknown",
            "latest_report_date": max(dates).isoformat() if dates else None,
            "updated_at": utc_stamp(max(fetched)) if fetched else None,
            "observed_days": len(dates),
            "missing_dates": [(start + timedelta(days=i)).isoformat() for i in range((end-start).days+1)
                              if start + timedelta(days=i) not in dates] if start and end else []}


def envelope(tenant_id, account_scope, source):
    from datetime import datetime, timezone
    return {"contract_version": "sem-cockpit-v1", "tenant_id": tenant_id, "module": "sem",
            "read_only": True, "is_demo": False, "source": source, "account_scope": account_scope,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "units": {"cost": "CNY", "click": "count", "impression": "count", "ctr": "ratio", "cpc": "CNY/click"}}


async def read_keywords(session, tenant_id, account_id, start, end, q, campaign_id, page, page_size):
    account_scope, _ = await accounts_for(session, tenant_id, account_id)
    if (start is None) != (end is None):
        raise HTTPException(422, "起止日期须同时提供或同时省略")
    mode = "explicit" if start else "latest_report_7d"
    if start:
        validate_window(start, end)
    else:
        end = await session.scalar(select(func.max(KwReportSnapshot.report_date)).where(*account_data_scope(KwReportSnapshot, tenant_id, account_scope)))
        start = end - timedelta(days=6) if end else None
    cond = account_data_scope(Keyword, tenant_id, account_scope)
    if q:
        cond.append(Keyword.keyword.contains(q, autoescape=True))
    if campaign_id is not None:
        cond.append(Keyword.campaign_id == campaign_id)
    total = await session.scalar(select(func.count()).select_from(Keyword).where(*cond))
    account_scope["observed_account_ids"] = list((await session.scalars(select(Keyword.baidu_account_id).where(*cond).distinct().order_by(Keyword.baidu_account_id))).all())
    assets = (await session.execute(select(Keyword.keyword_id, Keyword.baidu_account_id, Keyword.keyword,
        Keyword.campaign_id, Keyword.adgroup_id, Keyword.price, Keyword.pause, Keyword.synced_at)
        .where(*cond).order_by(Keyword.keyword_id, Keyword.id).offset((page-1)*page_size).limit(page_size))).all()
    reports, phones = [], []
    if start and assets:
        report_cond = [*account_data_scope(KwReportSnapshot, tenant_id, account_scope), KwReportSnapshot.report_date >= start,
                       KwReportSnapshot.report_date <= end, KwReportSnapshot.keyword_id.in_([r.keyword_id for r in assets])]
        reports = (await session.execute(select(KwReportSnapshot.keyword_id, KwReportSnapshot.baidu_account_id,
            KwReportSnapshot.report_date, func.sum(KwReportSnapshot.cost).label("cost"),
            func.sum(KwReportSnapshot.click).label("click"), func.sum(KwReportSnapshot.impression).label("impression"),
            func.max(KwReportSnapshot.fetched_at).label("fetched_at")).where(*report_cond)
            .group_by(KwReportSnapshot.keyword_id, KwReportSnapshot.baidu_account_id, KwReportSnapshot.report_date))).all()
        phones = await read_phone_rows(session, report_cond, (KwReportSnapshot.keyword_id, KwReportSnapshot.baidu_account_id))
    by_key, by_keyword, phone_by_key = defaultdict(list), defaultdict(list), defaultdict(list)
    for r in reports:
        by_key[(r.baidu_account_id, r.keyword_id)].append(r)
        by_keyword[r.keyword_id].append(r)
    for r in phones:
        phone_by_key[(r.baidu_account_id, r.keyword_id)].append(r)
    items = []
    for a in assets:
        key = (a.baidu_account_id, a.keyword_id)
        # NULL ownership is not a shared account identity. Two unassigned rows
        # may originate from different Baidu accounts, so never join them.
        ownership_unknown = a.baidu_account_id is None
        matched_reports = [] if ownership_unknown else by_key[key]
        keyword_reports = by_keyword[a.keyword_id]
        other_report_accounts = sorted({
            r.baidu_account_id for r in keyword_reports
            if r.baidu_account_id is not None and r.baidu_account_id != a.baidu_account_id
        })
        has_unassigned_reports = any(r.baidu_account_id is None for r in keyword_reports)
        if ownership_unknown:
            evidence_status = "ownership_unknown"
        elif matched_reports:
            evidence_status = "matched"
        elif other_report_accounts:
            evidence_status = "account_mismatch"
        elif has_unassigned_reports:
            evidence_status = "report_ownership_unknown"
        else:
            evidence_status = "no_report"
        # Keep the original three-state fields valid for already-loaded clients.
        # The additive evidence fields carry the stricter five-state meaning.
        association_status = (
            evidence_status if evidence_status in {"matched", "account_mismatch", "no_report"} else "no_report"
        )
        items.append({"keyword_id": a.keyword_id, "baidu_account_id": a.baidu_account_id,
                      "keyword": a.keyword, "campaign_id": a.campaign_id, "adgroup_id": a.adgroup_id,
                      "price": float(a.price) if a.price is not None else None, "pause": a.pause,
                      "asset_updated_at": utc_stamp(a.synced_at),
                      "metrics": report_metrics(matched_reports), "coverage": coverage(matched_reports, start, end),
                      "report_association": {
                          "status": association_status,
                          "evidence_status": evidence_status,
                          "join_keys": ["baidu_account_id", "keyword_id"],
                          "matched_report_groups": len(matched_reports),
                          "other_observed_account_ids": (
                              other_report_accounts if association_status == "account_mismatch" else []
                          ),
                          "observed_known_account_ids": other_report_accounts,
                          "has_unassigned_reports": has_unassigned_reports,
                          "completeness": "unknown",
                      },
                      "phone_button_clicks": phone_summary([] if ownership_unknown else phone_by_key[key])})
    association_counts = {status: 0 for status in ("matched", "account_mismatch", "no_report")}
    evidence_counts = {status: 0 for status in (
        "matched", "account_mismatch", "no_report", "ownership_unknown", "report_ownership_unknown"
    )}
    for item in items:
        association_counts[item["report_association"]["status"]] += 1
        evidence_counts[item["report_association"]["evidence_status"]] += 1
    return {**envelope(tenant_id, account_scope, "keywords+kw_report_snapshots"),
            "window": window(start, end, mode), "filters": {"q": q, "campaign_id": campaign_id},
            "page": page, "page_size": page_size, "total": total, "items": items,
            "association_summary": {"scope": "current_page", "counts": association_counts,
                                    "evidence_counts": evidence_counts,
                                    "completeness": "unknown"},
            "scope_note": "关键词资产列表；只关联相同非空账户与关键词ID的报告，未归属记录不推断到其他账户"}


async def read_dimensions(session, tenant_id, account_scope, keyword_id, start, end, expected):
    result = {}
    for model, name, cols in (
        (KeywordRegionReport, "region", (KeywordRegionReport.region_name, KeywordRegionReport.region_level)),
        (KeywordHourlyReport, "schedule", (KeywordHourlyReport.report_datetime, KeywordHourlyReport.hour)),
    ):
        rows = (await session.execute(select(model.baidu_account_id, model.report_date, *cols,
            func.sum(model.cost).label("cost"), func.sum(model.click).label("click"),
            func.sum(model.impression).label("impression"), func.max(model.fetched_at).label("fetched_at"))
            .where(*account_data_scope(model, tenant_id, account_scope), model.keyword_id == keyword_id,
                   model.report_date >= start, model.report_date <= end)
            .group_by(model.baidu_account_id, model.report_date, *cols))).all()
        groups = defaultdict(list)
        for row in rows:
            key = (row.region_level, row.region_name) if name == "region" else (row.report_datetime.isoweekday(), row.hour)
            groups[key].append(row)
        payload = {"source": model.__tablename__, "window": window(start, end), "coverage": coverage(rows, start, end),
                   "accounts": [{"baidu_account_id": aid, "coverage": coverage([r for r in rows if r.baidu_account_id == aid], start, end)}
                                for aid in sorted(set(expected) | {r.baidu_account_id for r in rows}, key=lambda x: (x is None, x or 0))]}
        if name == "region":
            payload["rows"] = [{"region_level": key[0], "region_name": key[1], "metrics": report_metrics(items)}
                               for key, items in sorted(groups.items())]
            payload["totals_by_level"] = [{"region_level": level, "metrics": report_metrics([r for r in rows if r.region_level == level])}
                                          for level in sorted({r.region_level for r in rows})]
            payload["scope_note"] = "单关键词省/市分别统计，不跨层级相加"
        else:
            payload["dimension"] = "weekday_hour"
            payload["cells"] = [{"weekday": day, "hour": hour, "status": "observed" if (day,hour) in groups else "no_data",
                                  "metrics": report_metrics(groups.get((day,hour), []))}
                                 for day in range(1,8) for hour in range(24)]
            payload["metrics"] = report_metrics(rows)
        result[name] = payload
    return result


async def read_keyword_detail(session, tenant_id, account_id, keyword_id, start, end):
    validate_window(start, end)
    account_scope, _ = await accounts_for(session, tenant_id, account_id)
    assets = (await session.execute(select(Keyword.baidu_account_id, Keyword.keyword, Keyword.synced_at)
              .where(*account_data_scope(Keyword, tenant_id, account_scope), Keyword.keyword_id == keyword_id)
              .order_by(Keyword.baidu_account_id))).all()
    if not assets:
        exists = await session.scalar(select(KwReportSnapshot.keyword_id).where(*account_data_scope(KwReportSnapshot, tenant_id, account_scope), KwReportSnapshot.keyword_id == keyword_id).limit(1))
        if exists is None:
            raise HTTPException(404, "该范围不存在此关键词")
    result = await read_report(session, tenant_id, start, end, account_id, keyword_id)
    phone_rows = await read_phone_rows(session, [*account_data_scope(KwReportSnapshot, tenant_id, account_scope),
        KwReportSnapshot.keyword_id == keyword_id, KwReportSnapshot.report_date >= start,
        KwReportSnapshot.report_date <= end], (KwReportSnapshot.baidu_account_id,))
    result["phone_button_clicks"] = phone_summary(phone_rows)
    for account in result["accounts"]:
        account["phone_button_clicks"] = phone_summary([r for r in phone_rows if r.baidu_account_id == account["baidu_account_id"]])
    result["unavailable"].pop("phone_button_clicks", None)
    result["keyword_id"] = keyword_id
    result["keyword_assets"] = [{"baidu_account_id": a.baidu_account_id, "keyword": a.keyword,
                                  "asset_updated_at": utc_stamp(a.synced_at)} for a in assets]
    result["dimensions"] = await read_dimensions(session, tenant_id, account_scope, keyword_id, start, end,
                                                 [a["baidu_account_id"] for a in result["accounts"]])
    return result


def nullable_metrics(rows):
    values = {}
    for field in ("cost", "click", "impression"):
        observed = [getattr(r, field) for r in rows if getattr(r, field) is not None]
        values[field] = sum(observed) if rows and len(observed) == len(rows) else None
    cost, click, imp = values["cost"], values["click"], values["impression"]
    return {"cost": round(float(cost),2) if cost is not None else None,
            "click": click, "impression": imp,
            "ctr": round(click/imp,6) if click is not None and imp else None,
            "cpc": round(float(cost)/click,2) if cost is not None and click else None}


async def read_search_terms(session, tenant_id, account_id, q, campaign_id, adgroup_id, page, page_size):
    account_scope, _ = await accounts_for(session, tenant_id, account_id)
    cond = account_data_scope(SearchTermReport, tenant_id, account_scope)
    if q:
        cond.append(SearchTermReport.query_word.contains(q, autoescape=True))
    for field, value in ((SearchTermReport.campaign_id,campaign_id),(SearchTermReport.adgroup_id,adgroup_id)):
        if value is not None:
            cond.append(field == value)
    total = await session.scalar(select(func.count()).select_from(SearchTermReport).where(*cond))
    rows = (await session.execute(select(SearchTermReport.id, SearchTermReport.baidu_account_id, SearchTermReport.query_word,
        SearchTermReport.trigger_keyword, SearchTermReport.campaign_id, SearchTermReport.adgroup_id,
        SearchTermReport.cost, SearchTermReport.click, SearchTermReport.impression,
        SearchTermReport.window_start, SearchTermReport.window_end, SearchTermReport.synced_at)
        .where(*cond).order_by(SearchTermReport.id).offset((page-1)*page_size).limit(page_size))).all()
    # Group the full filtered set, not just the current page; never sum across windows.
    groups = (await session.execute(select(SearchTermReport.baidu_account_id, SearchTermReport.window_start, SearchTermReport.window_end,
        func.min(SearchTermReport.synced_at).label("oldest_updated_at"), func.max(SearchTermReport.synced_at).label("updated_at"),
        func.count().label("row_count"), func.count(SearchTermReport.synced_at).label("timestamp_count"))
        .where(*cond).group_by(SearchTermReport.baidu_account_id, SearchTermReport.window_start, SearchTermReport.window_end))).all()
    windows = [{"baidu_account_id": g.baidu_account_id, **window(g.window_start,g.window_end,"sync_snapshot"),
                "stored_rows": g.row_count, "updated_at": utc_stamp(g.updated_at),
                "oldest_updated_at": utc_stamp(g.oldest_updated_at), "unknown_timestamp_rows": g.row_count-g.timestamp_count,
                "completeness": "unknown"} for g in groups]
    account_scope["observed_account_ids"] = sorted({g.baidu_account_id for g in groups}, key=lambda x: (x is None, x or 0))
    return {**envelope(tenant_id, account_scope, "search_term_reports"),
            "filters": {"q": q, "campaign_id": campaign_id, "adgroup_id": adgroup_id},
            "windows": windows, "mixed_windows": len({(g.window_start,g.window_end) for g in groups}) > 1,
            "status": "observed" if total else "no_data", "completeness": "unknown",
            "page": page, "page_size": page_size, "total": total,
            "items": [{"id": r.id, "baidu_account_id": r.baidu_account_id, "query_word": r.query_word,
                       "trigger_keyword": r.trigger_keyword, "campaign_id": r.campaign_id, "adgroup_id": r.adgroup_id,
                       "metrics": nullable_metrics([r]), "window": window(r.window_start,r.window_end,"sync_snapshot"),
                       "updated_at": utc_stamp(r.synced_at)} for r in rows],
            "scope_note": "仅同步窗口快照，无每日历史；触发词文本不是点击级归因；不返回跨窗口总量"}
