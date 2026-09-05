"""SEM 效果验证共用查询与自然日报表窗口，不触及回写。"""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from app.models import AdjustmentReview

REVIEW_PREFIX = "sem-review-v1:"


def report_today():
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def effect_window(action_date, latest, next_date=None):
    # 日报无法拆分操作当天；当日及下次操作当天均不归因。
    start = action_date + timedelta(days=1)
    end = min(latest, report_today() - timedelta(days=1)) if latest else None
    if end and next_date:
        end = min(end, next_date - timedelta(days=1))
    return start, end


def window_info(start, end, next_date):
    return {
        "timezone": "Asia/Shanghai", "after_from": start.isoformat(),
        "after_through": end.isoformat() if end and end >= start else None,
        "next_adjustment_date": next_date.isoformat() if next_date else None,
        "message": "按北京时间完整自然日对比，排除调整当天；遇下次调整截断，不代表因果收益",
    }


async def select_review_page(session, model, key, conditions, order, status, offset, limit):
    review_status = func.coalesce(AdjustmentReview.status, "pending")
    query = select(model).outerjoin(AdjustmentReview, (
        (AdjustmentReview.tenant_id == model.tenant_id) & (AdjustmentReview.dedup_key == key)
    )).where(*conditions)
    summary_rows = (await session.execute(
        query.with_only_columns(review_status, func.count()).group_by(review_status)
    )).all()
    counts = dict(summary_rows)
    summary = {"total": sum(counts.values()), "pending": counts.get("pending", 0),
               "verified": counts.get("verified", 0)}
    if status:
        query = query.where(review_status == status)
    total = summary[status] if status else summary["total"]
    rows = (await session.scalars(query.order_by(*order).offset(offset).limit(limit))).all()
    return rows, {"summary": summary, "total": total, "offset": offset, "limit": limit,
                  "has_more": offset + len(rows) < total, "counts_scope": "selected_date_range"}


def review_note(raw):
    if not raw or not raw.startswith(REVIEW_PREFIX):
        return raw, None
    try:
        evidence = json.loads(raw[len(REVIEW_PREFIX):])
        return evidence["note"], evidence
    except (ValueError, TypeError, KeyError):
        return None, None
