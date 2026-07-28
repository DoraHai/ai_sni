"""异常告警接口。

对应原型 02-monitor/02-alerts.html。
规则引擎产出见 app/rules/，本模块只做查询 + 状态流转 + 手动触发。
"""
import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Alert, Tenant
from app.rules import run_rules_for_tenant
from app.security.auth import require_scoped_auth

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/alerts",
    tags=["异常告警"],
    dependencies=[Depends(require_scoped_auth)],
)

PRIORITY_ORDER = ["P0", "P1", "P2", "P3", "P4", "P5"]


def _alert_to_dict(a: Alert) -> dict:
    return {
        "id": a.id,
        "priority": a.priority,
        "title": a.title,
        "message": a.message,
        "report_date": a.report_date.isoformat(),
        "keyword_id": a.keyword_id,
        "keyword": a.keyword,
        "campaign_id": a.campaign_id,
        "campaign_name": a.campaign_name,
        "metrics": a.metrics or {},
        "status": a.status,
        # 来源：ai=AI 异常扫描（R-AI），rule=自研规则引擎
        "source": "ai" if a.rule_code == "R-AI" else "rule",
        "detected_at": a.detected_at.isoformat(),
        "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
    }


@router.get("")
async def list_alerts(
    tenant_id: int = Query(..., description="本地租户 ID"),
    status: str | None = Query(
        "open", description="open / resolved / merged，传 all 看全部"
    ),
    priority: str | None = Query(None, description="P0~P5，不传看全部"),
    limit: int = Query(100, le=500),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """告警列表 + 按优先级计数。默认只看未处理。

    同一规则同一关键词多天触发时只有最新一条是 open（旧的被引擎归并为 merged），
    open 告警附带 streak（近期累计触发天数 + 首次日期）。
    """
    cond = [Alert.tenant_id == tenant_id]
    if status and status != "all":
        cond.append(Alert.status == status)
    if priority:
        cond.append(Alert.priority == priority)

    rows = (
        await session.scalars(
            select(Alert)
            .where(*cond)
            .order_by(Alert.priority, Alert.report_date.desc(), Alert.id.desc())
            .limit(limit)
        )
    ).all()

    # 同组（规则+关键词）累计触发统计：open + merged 计入，人工 resolved 算已处理完的旧事不计
    streak_rows = (
        await session.execute(
            select(
                Alert.rule_code,
                Alert.keyword_id,
                func.count(),
                func.min(Alert.report_date),
            )
            .where(
                Alert.tenant_id == tenant_id,
                Alert.keyword_id.isnot(None),
                Alert.status.in_(["open", "merged"]),
            )
            .group_by(Alert.rule_code, Alert.keyword_id)
            .having(func.count() > 1)
        )
    ).all()
    streaks = {
        (rc, kw): {"days": int(n), "first_date": d.isoformat()}
        for rc, kw, n, d in streak_rows
    }

    # 未处理告警按优先级计数（不受 priority 筛选影响，给看板/侧边栏角标用）
    count_rows = (
        await session.execute(
            select(Alert.priority, func.count())
            .where(Alert.tenant_id == tenant_id, Alert.status == "open")
            .group_by(Alert.priority)
        )
    ).all()
    counts = {p: 0 for p in PRIORITY_ORDER}
    counts.update({p: int(n) for p, n in count_rows})

    alerts = []
    for a in rows:
        item = _alert_to_dict(a)
        if a.status == "open":
            item["streak"] = streaks.get((a.rule_code, a.keyword_id))
        alerts.append(item)

    return {
        "open_counts": counts,
        "total_open": sum(counts.values()),
        "alerts": alerts,
    }


@router.patch("/{alert_id}/resolve")
async def resolve_alert(
    alert_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """标记告警为已处理。"""
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(404, "告警不存在，可能已被删除")
    if alert.status != "resolved":
        alert.status = "resolved"
        alert.resolved_at = datetime.utcnow()
        await session.commit()
    return {"status": "ok", "alert": _alert_to_dict(alert)}


@router.post("/run")
async def run_rules(
    tenant_id: int = Query(..., description="本地租户 ID"),
    target_date: date = Query(..., description="目标日期 YYYY-MM-DD"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """手动触发规则引擎（正常情况由每日定时任务自动跑）。"""
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在，请确认 tenant_id")
    n = await run_rules_for_tenant(session, tenant, target_date)
    return {"status": "ok", "tenant_id": tenant_id, "date": target_date.isoformat(), "alerts_written": n}
