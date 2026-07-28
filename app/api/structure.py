"""账户结构列表：计划列表 / 单元列表（工作台视图 tabs）。

只读本地维度表 + 快照聚合，不调百度。7 天指标窗口与关键词列表同口径
（锚定租户最近有数据的日期）。
"""
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dashboard import _f
from app.database import get_session
from app.models import Adgroup, Campaign, Keyword, KwReportSnapshot, Lead
from app.security.auth import require_scoped_auth

router = APIRouter(
    prefix="/api/v1/structure",
    tags=["账户结构"],
    dependencies=[Depends(require_scoped_auth)],
)


async def _metrics_7d_by(
    session: AsyncSession, tenant_id: int, group_col
) -> dict[int, dict[str, Any]]:
    """近 7 天指标按计划/单元聚合。返回 {id: {cost, click, impression}}。"""
    max_date = await session.scalar(
        select(func.max(KwReportSnapshot.report_date)).where(
            KwReportSnapshot.tenant_id == tenant_id
        )
    )
    if max_date is None:
        return {}
    rows = (
        await session.execute(
            select(
                group_col,
                func.sum(KwReportSnapshot.cost),
                func.sum(KwReportSnapshot.click),
                func.sum(KwReportSnapshot.impression),
            )
            .where(
                KwReportSnapshot.tenant_id == tenant_id,
                KwReportSnapshot.report_date >= max_date - timedelta(days=6),
                KwReportSnapshot.report_date <= max_date,
                group_col.isnot(None),
            )
            .group_by(group_col)
        )
    ).all()
    return {
        int(r[0]): {"cost": _f(r[1]), "click": int(r[2]), "impression": int(r[3])}
        for r in rows
    }


async def _leads_by_campaign(session: AsyncSession, tenant_id: int) -> dict[int, int]:
    """累计有效线索数按计划聚合（排除无效、排除账户级 campaign_id 为空的）。"""
    rows = (
        await session.execute(
            select(Lead.campaign_id, func.count())
            .where(
                Lead.tenant_id == tenant_id,
                Lead.status != "invalid",
                Lead.campaign_id.isnot(None),
            )
            .group_by(Lead.campaign_id)
        )
    ).all()
    return {int(r[0]): int(r[1]) for r in rows}


async def _cost_total_by_campaign(session: AsyncSession, tenant_id: int) -> dict[int, float]:
    """累计消费按计划聚合（全窗口，给累计线索成本当分子）。"""
    rows = (
        await session.execute(
            select(KwReportSnapshot.campaign_id, func.sum(KwReportSnapshot.cost))
            .where(
                KwReportSnapshot.tenant_id == tenant_id,
                KwReportSnapshot.campaign_id.isnot(None),
            )
            .group_by(KwReportSnapshot.campaign_id)
        )
    ).all()
    return {int(r[0]): _f(r[1]) for r in rows}


async def _counts_by(session: AsyncSession, tenant_id: int, model, group_col) -> dict[int, int]:
    rows = (
        await session.execute(
            select(group_col, func.count())
            .where(model.tenant_id == tenant_id, group_col.isnot(None))
            .group_by(group_col)
        )
    ).all()
    return {int(r[0]): int(r[1]) for r in rows}


@router.get("/campaigns")
async def list_campaigns(
    tenant_id: int = Query(..., description="本地租户 ID"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """计划列表：预算/状态/出价系数概览/移动比例 + 单元数/关键词数 + 7 天指标。"""
    campaigns = (
        await session.scalars(
            select(Campaign).where(Campaign.tenant_id == tenant_id)
        )
    ).all()
    adgroup_counts = await _counts_by(session, tenant_id, Adgroup, Adgroup.campaign_id)
    keyword_counts = await _counts_by(session, tenant_id, Keyword, Keyword.campaign_id)
    metrics = await _metrics_7d_by(session, tenant_id, KwReportSnapshot.campaign_id)
    lead_counts = await _leads_by_campaign(session, tenant_id)
    cost_totals = await _cost_total_by_campaign(session, tenant_id)

    rows = []
    for c in campaigns:
        sched = c.schedule_price_factors or []
        region = c.region_price_factor or []
        m = metrics.get(c.campaign_id, {})
        lead_n = lead_counts.get(c.campaign_id, 0)
        lead_cost = round(cost_totals.get(c.campaign_id, 0) / lead_n, 2) if lead_n else None
        rows.append(
            {
                "campaign_id": c.campaign_id,
                "campaign_name": c.campaign_name,
                "budget": _f(c.budget) if c.budget is not None else None,
                "pause": c.pause,
                "status": c.status,
                "equipment_type": c.equipment_type,  # 1=计算机 2=移动
                "price_ratio": _f(c.price_ratio) if c.price_ratio is not None else None,
                "schedule_entries": len(sched),
                "region_entries": len(region),
                "adgroup_count": adgroup_counts.get(c.campaign_id, 0),
                "keyword_count": keyword_counts.get(c.campaign_id, 0),
                "metrics_7d": {
                    "cost": m.get("cost"),
                    "click": m.get("click"),
                    "impression": m.get("impression"),
                },
                # 线索为累计口径（台账累计有效线索；成本=累计消费÷累计线索）
                "leads_total": lead_n,
                "lead_cost": lead_cost,
                "synced_at": c.synced_at.isoformat() if c.synced_at else None,
            }
        )
    rows.sort(key=lambda r: (r["metrics_7d"]["cost"] or 0), reverse=True)
    return {"total": len(rows), "campaigns": rows}


@router.get("/adgroups")
async def list_adgroups(
    tenant_id: int = Query(..., description="本地租户 ID"),
    campaign_id: int | None = Query(None, description="按计划筛选"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """单元列表：出价/移动比例/否词数 + 关键词数 + 7 天指标。"""
    cond = [Adgroup.tenant_id == tenant_id]
    if campaign_id is not None:
        cond.append(Adgroup.campaign_id == campaign_id)
    adgroups = (await session.scalars(select(Adgroup).where(*cond))).all()

    camp_names = {
        c.campaign_id: c.campaign_name
        for c in (
            await session.scalars(
                select(Campaign).where(Campaign.tenant_id == tenant_id)
            )
        ).all()
    }
    keyword_counts = await _counts_by(session, tenant_id, Keyword, Keyword.adgroup_id)
    metrics = await _metrics_7d_by(session, tenant_id, KwReportSnapshot.adgroup_id)

    rows = []
    for a in adgroups:
        m = metrics.get(a.adgroup_id, {})
        neg = len(a.negative_words or []) + len(a.exact_negative_words or [])
        rows.append(
            {
                "adgroup_id": a.adgroup_id,
                "adgroup_name": a.adgroup_name,
                "campaign_id": a.campaign_id,
                "campaign_name": camp_names.get(a.campaign_id),
                "max_price": _f(a.max_price) if a.max_price is not None else None,
                "pause": a.pause,
                "status": a.status,
                "price_ratio": _f(a.price_ratio) if a.price_ratio is not None else None,
                "pc_final_url": a.pc_final_url,
                "mobile_final_url": a.mobile_final_url,
                "pc_track_param": a.pc_track_param,
                "mobile_track_param": a.mobile_track_param,
                "pc_track_template": a.pc_track_template,
                "mobile_track_template": a.mobile_track_template,
                "negative_word_count": neg,
                "keyword_count": keyword_counts.get(a.adgroup_id, 0),
                "metrics_7d": {
                    "cost": m.get("cost"),
                    "click": m.get("click"),
                    "impression": m.get("impression"),
                },
            }
        )
    rows.sort(key=lambda r: (r["metrics_7d"]["cost"] or 0), reverse=True)
    return {"total": len(rows), "adgroups": rows}
