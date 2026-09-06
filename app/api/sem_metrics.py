"""SEM 客户级只读指标契约；不调用百度、不补采、不写入快照。"""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import BigInteger, bindparam, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import BaiduAccount, KwReportSnapshot, Tenant, WritebackApproval
from app.module_scope import ensure_module_access
from app.security.auth import AuthContext, require_auth
from app.security.sem_identity import load_sem_identity_states

router = APIRouter(prefix="/api/v1/sem/metrics", tags=["SEM 指标契约"])
TZ = ZoneInfo("Asia/Shanghai")

MetricKey = Literal[
    "sem.spend.month_to_date_cny", "sem.spend.budget_utilization_pct",
    "sem.accounts.active_count", "sem.approvals.pending_count",
    "sem.identity.conflict_tenant_count",
]


class MetricTrend(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    direction: Literal["up", "down", "flat"] | None
    change_pct: float | None
    change_abs: float | None


class MetricSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    metric_key: MetricKey
    value: float | int | None
    unit: Literal["CNY", "percent", "account", "approval", "customer"]
    as_of: AwareDatetime | None
    trend_7d: MetricTrend | None
    definition: str = Field(min_length=1)
    data_status: Literal["available", "observed_reports", "identity_blocked",
                         "no_reports", "unattributed_reports", "no_budget"]

    @model_validator(mode="after")
    def validate_contract(self):
        units = dict(zip(MetricKey.__args__, ("CNY", "percent", "account", "approval", "customer")))
        if self.unit != units[self.metric_key]:
            raise ValueError("metric unit does not match key")
        if self.data_status not in {"available", "observed_reports"} and self.value is not None:
            raise ValueError("unavailable metric must have null value")
        if self.value is not None and self.as_of is None:
            raise ValueError("observed value requires as_of")
        if self.trend_7d is not None and self.value is None:
            raise ValueError("unavailable metric cannot have a trend")
        return self


class MetricSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: int = Field(gt=0)
    items: list[MetricSnapshot] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def require_all_metrics(self):
        if {item.metric_key for item in self.items} != set(MetricKey.__args__):
            raise ValueError("snapshot requires each SEM metric exactly once")
        return self


def metric(key, value, unit, as_of, definition, *, trend=None, status="available"):
    return {
        "metric_key": f"sem.{key}", "value": value, "unit": unit,
        "as_of": as_of.isoformat() if as_of else None,
        "trend_7d": trend, "definition": definition, "data_status": status,
    }


def compare_seven_days(current: Decimal, previous: Decimal) -> dict:
    """Direction is factual only; a zero baseline has no defined percent change."""
    delta = current - previous
    return {
        "direction": "up" if delta > 0 else "down" if delta < 0 else "flat",
        "change_pct": float(delta / abs(previous) * 100) if previous else None,
        "change_abs": float(delta),
    }


def month_spend_trend(month_rows, month_start, end):
    baseline = end - timedelta(days=7)
    if baseline < month_start:
        return None
    days = [month_start + timedelta(days=offset) for offset in range((end - month_start).days + 1)]
    # Missing dates are not zero. Do not compare incomplete month totals.
    if any(day not in month_rows or not month_rows[day][1] for day in days):
        return None
    current = sum((month_rows[day][0] for day in days), Decimal(0))
    previous = sum((month_rows[day][0] for day in days if day <= baseline), Decimal(0))
    return compare_seven_days(current, previous)


@router.get("/snapshot", response_model=MetricSnapshotResponse)
async def snapshot(
    tenant_id: int = Query(..., gt=0),
    ctx: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ctx.ensure_tenant(tenant_id)
    # This composite endpoint must not bypass the approval ledger's view permission.
    if not (ctx.can_view("monitor.dashboard") and ctx.can_view("verify.adjustments")):
        raise HTTPException(403, "需要数据看板及效果验证查看权限")
    await ensure_module_access(session, ctx, tenant_id, "sem")
    # Keep the old small-ID path compatible; bind large IDs explicitly because
    # the shared Tenant ORM still declares INTEGER while production is BIGINT.
    # Do not alter that shared model (or SEO/GEO) as part of this SEM change.
    if tenant_id > 2**31 - 1:
        tenant = await session.scalar(select(Tenant).where(
            Tenant.id == bindparam("sem_metric_tenant_id", tenant_id, type_=BigInteger),
        ))
    else:
        tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "客户不存在")
    now = datetime.now(TZ)
    today = now.date()
    end = today - timedelta(days=1)
    month_start = today.replace(day=1)
    start = month_start
    identity = (await load_sem_identity_states(session, [tenant_id]))[tenant_id]
    blocked = identity["status"] == "blocked"
    items = [metric(
        "identity.conflict_tenant_count", int(blocked), "customer", now,
        "当前请求客户存在隔离标记或生效 UCID 跨客户重复时为 1，否则为 0；不是全站客户数。",
    )]
    if blocked:
        for key, unit, definition in (
            ("spend.month_to_date_cny", "CNY", "本月截至昨日的已归属关键词报表花费合计，不是实时账户总花费。"),
            ("spend.budget_utilization_pct", "percent", "本月已归属关键词报表花费除以当前客户月预算乘 100。"),
            ("accounts.active_count", "account", "当前客户状态为 active 的本地推广账户记录数，不验证远端 token 有效性。"),
            ("approvals.pending_count", "approval", "当前客户审批表中 status=pending 的记录数，不含已批准或已消费记录。"),
        ):
            items.append(metric(key, None, unit, None, definition, status="identity_blocked"))
        return {"tenant_id": tenant_id, "items": items}

    active = await session.scalar(select(func.count()).select_from(BaiduAccount).where(
        BaiduAccount.tenant_id == tenant_id, BaiduAccount.status == "active",
    ))
    pending = await session.scalar(select(func.count()).select_from(WritebackApproval).where(
        WritebackApproval.tenant_id == tenant_id, WritebackApproval.status == "pending",
    ))
    # Outer join detects unattributed or cross-tenant report rows instead of silently
    # dropping their cost and presenting an understated month total.
    rows = (await session.execute(
        select(KwReportSnapshot.report_date, func.sum(KwReportSnapshot.cost),
               func.count(), func.count(BaiduAccount.id))
        .outerjoin(BaiduAccount, (BaiduAccount.id == KwReportSnapshot.baidu_account_id)
                   & (BaiduAccount.tenant_id == tenant_id))
        .where(KwReportSnapshot.tenant_id == tenant_id,
               KwReportSnapshot.report_date >= start, KwReportSnapshot.report_date <= end)
        .group_by(KwReportSnapshot.report_date)
    )).all()
    daily = {day: (Decimal(cost), count == attributed) for day, cost, count, attributed in rows}
    month_rows = {day: row for day, row in daily.items() if day >= month_start}
    valid = bool(month_rows) and all(ok for _, ok in month_rows.values())
    amount = sum((cost for cost, _ in month_rows.values()), Decimal(0)) if valid else None
    status = "observed_reports" if valid else ("unattributed_reports" if month_rows else "no_reports")
    as_of = datetime.combine(max(month_rows), datetime.min.time(), TZ) if valid else None
    budget = tenant.monthly_budget
    utilization = round(float(amount / budget * 100), 2) if amount is not None and budget and budget > 0 else None
    trend = month_spend_trend(month_rows, month_start, end)
    items.extend([
        metric("spend.month_to_date_cny", float(amount) if amount is not None else None, "CNY", as_of,
               "本月截至昨日的已归属关键词报表花费合计，不是实时账户总花费；缺报日期不推算。",
               trend=trend, status=status),
        metric("spend.budget_utilization_pct", utilization, "percent", as_of,
               "本月已归属关键词报表花费除以当前客户月预算乘 100；未配置正数预算时为空。",
               status=status if budget and budget > 0 else "no_budget"),
        metric("accounts.active_count", active, "account", now,
               "当前客户状态为 active 的本地推广账户记录数，不验证远端 token 有效性。"),
        metric("approvals.pending_count", pending, "approval", now,
               "当前客户审批表中 status=pending 的记录数，不含已批准或已消费记录。"),
    ])
    return {"tenant_id": tenant_id, "items": items}
