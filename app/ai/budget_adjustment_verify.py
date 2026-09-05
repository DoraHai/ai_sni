"""预算调整效果验证（效果验证 / 预算维度）。

数据源是平台写回台账 writeback_actions，而不是百度后台真实操作回传。
复用 adjustment_reviews 表，使用预算专属 dedup_key 命名空间，避免和关键词调价验证冲突。
"""
import hashlib
from datetime import date, datetime, timedelta

from sqlalchemy import String, case, cast, func, select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdjustmentReview, Alert, KwReportSnapshot, Tenant, WritebackAction
from app.ai.effect_verification import effect_window, window_info, select_review_page, review_note

BEFORE_DAYS = 7
MAX_ITEMS = 50


def _budget_key_sql():
    account = WritebackAction.action_type == "set_account_budget"
    scope = case((account, "account"), else_="campaign")
    entity = case((account, WritebackAction.baidu_account_id), else_=WritebackAction.campaign_id)
    return func.md5("budget|" + scope + "|" + cast(entity, String) + "|" + cast(WritebackAction.id, String))


def _action_time(rec):
    # executed_at 由写回代码写入 naive UTC；历史 created_at 为数据库本地时间。
    return rec.executed_at + timedelta(hours=8) if rec.executed_at else rec.created_at


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
    baidu_account_id: int | None,
) -> float | None:
    """指定账户/计划的有报表日均消费，缺报不当作零消费。"""
    if start > end or baidu_account_id is None:
        return None
    cond = [
        KwReportSnapshot.tenant_id == tenant_id,
        KwReportSnapshot.baidu_account_id == baidu_account_id,
        KwReportSnapshot.report_date >= start,
        KwReportSnapshot.report_date <= end,
    ]
    if campaign_id is not None:
        cond.append(KwReportSnapshot.campaign_id == campaign_id)
    total, days = (await session.execute(select(
        func.sum(KwReportSnapshot.cost),
        func.count(func.distinct(KwReportSnapshot.report_date)),
    ).where(*cond))).one()
    return round(float(total or 0) / days, 2) if days else None


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
    baidu_account_id: int | None,
) -> dict:
    if baidu_account_id is None:
        return {"days": 0, "cost_per_day": None, "usage_pct": None, "overrun_day_pct": None}
    cost_per_day = await _daily_cost(session, tenant_id, start, end, campaign_id, baidu_account_id)
    usage_pct = round(cost_per_day / budget * 100, 1) if budget and cost_per_day is not None else None
    overrun_pct = await _overrun_rate(session, tenant_id, entity_ref, start, end)
    data_days = await session.scalar(
        select(func.count(func.distinct(KwReportSnapshot.report_date))).where(
            KwReportSnapshot.tenant_id == tenant_id,
            KwReportSnapshot.baidu_account_id == baidu_account_id,
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
    offset: int = 0, limit: int = MAX_ITEMS, paged: bool = False,
    dedup_key: str | None = None,
) -> list[dict]:
    """近 days 天的预算调整 + 调前/后使用率、撞线率对比。"""
    tid = tenant.id
    since_dt = datetime.utcnow() - timedelta(days=days)

    conditions = [
                WritebackAction.tenant_id == tid,
                WritebackAction.action_type.in_(
                    ["set_account_budget", "set_campaign_budget"]
                ),
                WritebackAction.status == "success",
                WritebackAction.dry_run.is_(False),
                or_(and_(WritebackAction.action_type == "set_account_budget", WritebackAction.baidu_account_id.is_not(None)),
                    and_(WritebackAction.action_type == "set_campaign_budget", WritebackAction.campaign_id.is_not(None))),
    ]
    conditions.append(_budget_key_sql() == dedup_key if dedup_key else WritebackAction.created_at >= since_dt)
    recs, page = await select_review_page(session, WritebackAction, _budget_key_sql(), conditions,
        [WritebackAction.created_at.desc(), WritebackAction.id.desc()], status, offset, limit)
    if not recs:
        return {**page, "items": []} if paged else []

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

        action_date = _action_time(rec).date()
        entity_ref = f"{scope}:{entity_id}"
        campaign_id = entity_id if scope == "campaign" else None
        latest = (await session.scalar(select(func.max(KwReportSnapshot.report_date)).where(
            KwReportSnapshot.tenant_id == tid,
            KwReportSnapshot.baidu_account_id == rec.baidu_account_id,
            *([KwReportSnapshot.campaign_id == campaign_id] if campaign_id is not None else []),
        ))) if rec.baidu_account_id is not None else None
        old_budget = float(rec.old_value) if rec.old_value is not None else None
        new_budget = float(rec.new_value) if rec.new_value is not None else None
        neighbors = (await session.scalars(select(WritebackAction).where(
            WritebackAction.tenant_id == tid,
            WritebackAction.baidu_account_id == rec.baidu_account_id,
            WritebackAction.action_type == rec.action_type,
            WritebackAction.id != rec.id, WritebackAction.status == "success",
            WritebackAction.dry_run.is_(False),
            *([WritebackAction.campaign_id == campaign_id] if campaign_id is not None else []),
        ))).all() if rec.baidu_account_id is not None else []
        later = [_action_time(r) for r in neighbors if _action_time(r) >= _action_time(rec)]
        next_date = min(later).date() if later else None
        start, end = effect_window(action_date, latest, next_date)
        window = window_info(start, end, next_date)

        before = await _window_budget_metrics(
            session,
            tid,
            campaign_id,
            entity_ref,
            old_budget,
            action_date - timedelta(days=BEFORE_DAYS),
            action_date - timedelta(days=1),
            rec.baidu_account_id,
        )
        after = (
            await _window_budget_metrics(
                session, tid, campaign_id, entity_ref, new_budget, start, end, rec.baidu_account_id
            )
            if end and end >= start
            else None
        )
        if rec.baidu_account_id is None:
            sample = {"state": "unmatched", "message": "缺少明确的百度账户归属，暂不能计算效果"}
        elif not before["days"]:
            sample = {"state": "missing_before", "message": "缺少调整前报表，暂不能对比"}
        elif after is None:
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
                "baidu_account_id": rec.baidu_account_id,
                "execution_status": rec.status,
                "dry_run": rec.dry_run,
                "campaign_name": rec.campaign_name,
                "action_time": _action_time(rec).isoformat(),
                "old_budget": old_budget,
                "new_budget": new_budget,
                "change_pct": (
                    round((new_budget - old_budget) / old_budget * 100, 1)
                    if old_budget and new_budget is not None
                    else None
                ),
                "effect": {
                    "before": before,
                    "after": after,
                    "after_through": window["after_through"],
                    "window": window,
                    "sample": sample,
                },
                "review": {
                    "status": review_status,
                    "verdict": rv.verdict if rv else None,
                    "note": review_note(rv.note)[0] if rv else None,
                    "evidence": review_note(rv.note)[1] if rv else None,
                    "verified_at": (
                        rv.verified_at.isoformat() if rv and rv.verified_at else None
                    ),
                },
            }
        )
    return {**page, "items": items} if paged else items
