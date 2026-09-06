"""Pure-query SEM cockpit contract; no live API, cache or task writes."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import String, func, literal, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement

from app.models import BaiduAccount, KwReportSnapshot


class _SourceJSONType(FunctionElement):
    """Preserve source booleans vs numbers across PostgreSQL and test SQLite."""
    type = String()
    inherit_cache = True


@compiles(_SourceJSONType, "postgresql")
def _postgres_json_type(element, compiler, **kw):
    column, key = list(element.clauses)
    return f"jsonb_typeof({compiler.process(column, **kw)} -> {compiler.process(key, **kw)})"


@compiles(_SourceJSONType, "sqlite")
def _sqlite_json_type(element, compiler, **kw):
    column, key = list(element.clauses)
    return f"json_type({compiler.process(column, **kw)}, '$.' || {compiler.process(key, **kw)})"


def validate_window(start: date, end: date) -> None:
    if start > end or (end - start).days >= 366:
        raise HTTPException(422, "日期范围须为顺序正确的 1 至 366 天（含首尾）")


def validate_query(params, allowed):
    if set(params) - allowed or any(len(params.getlist(k)) != 1 for k in params):
        raise HTTPException(422, "存在不支持或重复的筛选参数")


def utc_stamp(value):
    # Report ingestion stores naive UTC, not local Shanghai wall time.
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def report_metrics(rows):
    if not rows:
        return dict(cost=None, click=None, impression=None, ctr=None, cpc=None)
    cost = sum((r.cost for r in rows), Decimal(0))
    # PostgreSQL SUM(bigint) returns numeric/Decimal, unlike SQLite's integer.
    click = int(sum(r.click for r in rows))
    impression = int(sum(r.impression for r in rows))
    return dict(cost=round(float(cost), 2), click=click, impression=impression,
                ctr=round(click / impression, 6) if impression else None,
                cpc=round(float(cost) / click, 2) if click else None)


def phone_summary(rows):
    """Only explicit finite nonnegative integer source values are observations.

    Rows contain raw_value and row_count; no raw JSON or PII leaves this layer.
    Complete here means fields on stored rows, never complete source ingestion.
    """
    total = known = subtotal = 0
    for row in rows:
        total += row.row_count
        try:
            raw_value = row.raw_value if row.raw_type in {"number", "integer", "real", "string", "text"} else None
            value = Decimal(str(raw_value))
            valid = value.is_finite() and 0 <= value <= 9223372036854775807 and value == value.to_integral_value()
        except (InvalidOperation, ValueError):
            valid = False
        if valid:
            known += row.row_count
            subtotal += int(value) * row.row_count
    return {"value": subtotal if total and total == known else None,
            "known_subtotal": subtotal if known else None, "unit": "count",
            "source_field": "ocpcConversionsDetail2",
            "status": "no_data" if not total else "observed" if known == total else "partial" if known else "unavailable",
            "stored_rows": total, "known_rows": known, "unknown_rows": total - known,
            "completeness": "unknown"}


async def read_phone_rows(session, cond, group_columns=()):
    # Extract only the field, not whole raw report payloads. Preserve type before
    # dialect coercion so a JSON boolean cannot be mistaken for a numeric count.
    raw = KwReportSnapshot.raw_metrics["ocpcConversionsDetail2"].as_string()
    raw_type = _SourceJSONType(KwReportSnapshot.raw_metrics, literal("ocpcConversionsDetail2"))
    return (await session.execute(select(
        *group_columns, raw.label("raw_value"), raw_type.label("raw_type"), func.count().label("row_count")
    ).where(*cond).group_by(*group_columns, raw, raw_type))).all()


async def read_report(session, tenant_id, start, end, account_id, keyword_id=None):
    validate_window(start, end)
    accounts = (await session.execute(
        select(BaiduAccount.id, BaiduAccount.status)
        .where(BaiduAccount.tenant_id == tenant_id).order_by(BaiduAccount.id)
    )).all()
    if account_id is not None and account_id not in {a.id for a in accounts}:
        raise HTTPException(404, "该客户下不存在此账户")
    cond = [KwReportSnapshot.tenant_id == tenant_id,
            KwReportSnapshot.report_date >= start, KwReportSnapshot.report_date <= end]
    if account_id is not None:
        cond.append(KwReportSnapshot.baidu_account_id == account_id)
    if keyword_id is not None:
        cond.append(KwReportSnapshot.keyword_id == keyword_id)
    rows = (await session.execute(select(
        KwReportSnapshot.baidu_account_id, KwReportSnapshot.report_date,
        KwReportSnapshot.device,
        func.sum(KwReportSnapshot.cost).label("cost"),
        func.sum(KwReportSnapshot.click).label("click"),
        func.sum(KwReportSnapshot.impression).label("impression"),
        func.max(KwReportSnapshot.fetched_at).label("fetched_at"),
    ).where(*cond).group_by(KwReportSnapshot.baidu_account_id,
                           KwReportSnapshot.report_date, KwReportSnapshot.device))).all()
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    observed = {r.report_date for r in rows}
    # Row presence is evidence of observation, never proof of a complete import.
    def coverage(items):
        seen = {r.report_date for r in items}
        return {"status": "observed" if items else "no_data",
                "completeness": "unknown", "observed_days": len(seen),
                "missing_dates": [d.isoformat() for d in days if d not in seen],
                "latest_report_date": max(seen).isoformat() if seen else None,
                "updated_at": utc_stamp(max((r.fetched_at for r in items), default=None))}
    ids = {account_id} if account_id is not None else {a.id for a in accounts}
    ids |= {r.baidu_account_id for r in rows}
    return {
        "contract_version": "sem-cockpit-v1", "module": "sem", "is_demo": False,
        "read_only": True, "tenant_id": tenant_id,
        "window": {"start": start.isoformat(), "end": end.isoformat(),
                   "timezone": "Asia/Shanghai", "inclusive": True},
        "account_scope": {"mode": "all" if account_id is None else "single",
                          "baidu_account_id": account_id,
                          "includes_unassigned": any(r.baidu_account_id is None for r in rows)},
        "source": "kw_report_snapshots", "source_scope": "keyword_report_only",
        "units": {"cost": "CNY", "click": "count", "impression": "count",
                  "ctr": "ratio", "cpc": "CNY/click"},
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "coverage": coverage(rows), "metrics": report_metrics(rows),
        "accounts": [{"baidu_account_id": aid,
                      "status": next((a.status for a in accounts if a.id == aid), "unassigned"),
                      "metrics": report_metrics([r for r in rows if r.baidu_account_id == aid]),
                      "coverage": coverage([r for r in rows if r.baidu_account_id == aid])}
                     for aid in sorted(ids, key=lambda x: (x is None, x or 0))],
        "trend": [{"date": d.isoformat(), "status": "observed" if d in observed else "no_data",
                   **report_metrics([r for r in rows if r.report_date == d])} for d in days],
        "devices": [{"device": device, "label": {0: "PC", 1: "移动"}.get(device, "未知"),
                     **report_metrics([r for r in rows if r.device == device])}
                    for device in sorted({r.device for r in rows}, key=lambda x: (x is None, x or 0))],
        "unavailable": {"phone_button_clicks": "历史同步可能将缺失转化置零，暂不作为可信指标",
                        "valid_consultations": "尚无已核实有效咨询口径",
                        "account_balance": "本接口不调用实时账户 API"},
    }
