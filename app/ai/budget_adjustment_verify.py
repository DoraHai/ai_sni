"""预算调整效果验证（效果验证 / 预算维度）。

数据源是平台写回台账 writeback_actions，而不是百度后台真实操作回传。
复用 adjustment_reviews 表，使用预算专属 dedup_key 命名空间，避免和关键词调价验证冲突。
"""
import hashlib
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdjustmentReview, Alert, KwReportSnapshot, Tenant, WritebackAction

BEFORE_DAYS = 7
MAX_ITEMS = 50


def _budget_dedup_key(scope: str, entity_id: int, action_id: int) -> str:
    """scope: account / campaign. 32 位哈希适配 adjustment_reviews.dedup_key."""
    raw = f"budget|{scope}|{entity_id}|{action_id}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


async def _daily_cost(
    session: AsyncSession,
    tenant_id: int,
    start: date,
    end: date,
    campaign_id: int | None,
) -> float:
    """按日均消费聚合，campaign_id=None 时统计全账户。"""
    if start > end:
        return 0.0
    cond = [
        KwReportSnapshot.tenant_id == tenant_id,
        KwReportSnapshot.report_date >= start,
        KwReportSnapshot.report_date <= end,
    ]
    if campaign_id is not None:
        cond.append(KwReportSnapshot.campaign_id == campaign_id)
    total = await session.scalar(
        select(func.coalesce(func.sum(KwReportSnapshot.cost), 0)).where(*cond)
    )
    days = (end - start).days + 1
    return round(float(total or 0) / days, 2) if days > 0 else 0.0


async def _overrun_rate(
    session: AsyncSession,
    tenant_id: int,
    entity_ref: str,
    start: date,
    end: date,
) -> float | None:
    """窗口内 R-BUDGET 撞线告警天数 / 窗口天数。"""
    if start > end:
        return None
    cnt = await session.scalar(
        select(func.count(func.distinct(Alert.report_date))).where(
            Alert.tenant_id == tenant_id,
            Alert.rule_code == "R-BUDGET",
            Alert.entity_ref == entity_ref,
            Alert.report_date >= start,
            Alert.report_date <= end,
        )
    )
    days = (end - start).days + 1
    return round(int(cnt or 0) / days * 100, 1) if days > 0 else None


async def _window_budget_metrics(
    session: AsyncSession,
    tenant_id: int,
    campaign_id: int | None,
    entity_ref: str,
    budget: float | None,
    start: date,
    end: date,
) -> dict:
    cost_per_day = await _daily_cost(session, tenant_id, start, end, campaign_id)
    usage_pct = round(cost_per_day / budget * 100, 1) if budget else None
    overrun_pct = await _overrun_rate(session, tenant_id, entity_ref, start, end)
    data_days = await session.scalar(
        select(func.count(func.distinct(KwReportSnapshot.report_date))).where(
            KwReportSnapshot.tenant_id == tenant_id,
            KwReportSnapshot.report_date >= start,
            KwReportSnapshot.report_date <= end,
            *([KwReportSnapshot.campaign_id == campaign_id] if campaign_id is not None else []),
        )
    )
    return {
        "days": int(data_days or 0),
        "cost_per_day": cost_per_day,
        "usage_pct": usage_pct,
        "overrun_day_pct": overrun_pct,
    }


async def list_pending_budget(
    session: AsyncSession,
    tenant: Tenant,
    days: int = 7,
    status: str | None = None,
) -> list[dict]:
    """近 days 天的预算调整 + 调前/后使用率、撞线率对比。"""
    tid = tenant.id
    since_dt = datetime.utcnow() - timedelta(days=days)

    recs = (
        await session.scalars(
            select(WritebackAction)
            .where(
                WritebackAction.tenant_id == tid,
                WritebackAction.action_type.in_(
                    ["set_account_budget", "set_campaign_budget"]
                ),
                WritebackAction.created_at >= since_dt,
                WritebackAction.status.in_(["success", "dry_run"]),
            )
            .order_by(WritebackAction.created_at.desc())
            .limit(MAX_ITEMS)
        )
    ).all()
    if not recs:
        return []

    dedup_keys = []
    for rec in recs:
        scope = "account" if rec.action_type == "set_account_budget" else "campaign"
        entity_id = rec.baidu_account_id if scope == "account" else rec.campaign_id
        if entity_id is None:
            continue
        dedup_keys.append(_budget_dedup_key(scope, int(entity_id), rec.id))

    reviews = {
        rv.dedup_key: rv
        for rv in (
            await session.scalars(
                select(AdjustmentReview).where(
                    AdjustmentReview.tenant_id == tid,
                    AdjustmentReview.dedup_key.in_(dedup_keys),
                )
            )
        ).all()
    } if dedup_keys else {}

    latest = await session.scalar(
        select(func.max(KwReportSnapshot.report_date)).where(
            KwReportSnapshot.tenant_id == tid
        )
    )

    items = []
    for rec in recs:
        scope = "account" if rec.action_type == "set_account_budget" else "campaign"
        entity_id = rec.baidu_account_id if scope == "account" else rec.campaign_id
        if entity_id is None:
            continue
        entity_id = int(entity_id)
        dedup_key = _budget_dedup_key(scope, entity_id, rec.id)
        rv = reviews.get(dedup_key)
        review_status = rv.status if rv else "pending"
        if status and review_status != status:
            continue

        action_date = rec.created_at.date()
        entity_ref = f"{scope}:{entity_id}"
        campaign_id = entity_id if scope == "campaign" else None
        old_budget = float(rec.old_value) if rec.old_value is not None else None
        new_budget = float(rec.new_value) if rec.new_value is not None else None

        before = await _window_budget_metrics(
            session,
            tid,
            campaign_id,
            entity_ref,
            old_budget,
            action_date - timedelta(days=BEFORE_DAYS),
            action_date - timedelta(days=1),
        )
        after = (
            await _window_budget_metrics(
                session, tid, campaign_id, entity_ref, new_budget, action_date, latest
            )
            if latest and latest >= action_date
            else None
        )
        if after is None:
            sample = {"state": "collecting", "message": "调整后数据尚未同步"}
        elif after["days"] < 3:
            sample = {"state": "collecting", "message": f"调整后仅 {after['days']} 天，至少积累 3 天"}
        else:
            sample = {"state": "ready", "message": "样本已达到基础验证门槛"}

        items.append(
            {
                "dedup_key": dedup_key,
                "scope": scope,
                "entity_id": entity_id,
                "campaign_name": rec.campaign_name,
                "action_time": rec.created_at.isoformat(),
                "old_budget": old_budget,
                "new_budget": new_budget,
                "change_pct": (
                    round((new_budget - old_budget) / old_budget * 100, 1)
                    if old_budget
                    else None
                ),
                "effect": {
                    "before": before,
                    "after": after,
                    "after_through": latest.isoformat() if latest else None,
                    "sample": sample,
                },
                "review": {
                    "status": review_status,
                    "verdict": rv.verdict if rv else None,
                    "note": rv.note if rv else None,
                    "verified_at": (
                        rv.verified_at.isoformat() if rv and rv.verified_at else None
                    ),
                },
            }
        )
    return items
