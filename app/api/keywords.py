"""关键词接口：详情下钻 + 分级列表 + 人工改分级。

对应原型 02-monitor/03-keyword-detail.html。
详情 = 基础信息（分级/出价/质量度）+ 时段 KPI（含环比）+ 排名/消费趋势
       + 设备维度 + 关联告警。

原型里其余区块依赖尚未接入的数据源，本期返回 null 占位：
  - 出价系数 4 层叠加 → 需要计划/单元层级同步（M1 第二三周 campaign.py/adgroup.py）
  - 触发搜索词 → 需要搜索词报告（reportType 2307838）同步
  - 转化漏斗 / 线索 → M2 转化数据接入
  - 调价台账 → M2 调价写回 + getOperationRecord
"""
import csv
import io
import logging
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dashboard import DEVICE_LABELS, _change_pct, _derive, _f
from app.classification import classify_one, resolve_brand_terms
from app.database import get_session
from app.models import (
    CATEGORY_LABELS,
    QUERY_STATUS_LABELS,
    TARGET_RANK_LABELS,
    Adgroup,
    Alert,
    Campaign,
    Suggestion,
    Keyword,
    KeywordHourlyReport,
    KeywordRegionReport,
    KwReportSnapshot,
    PriceStrategy,
    SearchTermReport,
    Tenant,
)
from app.baidu.writeback import WritebackError, apply_keyword_writeback, apply_pause_writeback
from app.security.auth import AuthContext, require_scoped_auth

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/keywords",
    tags=["关键词详情"],
    dependencies=[Depends(require_scoped_auth)],
)

# 百度关键词报告 mixWmatchEnum 枚举（文档 0299）
MATCH_TYPE_LABELS = {
    0: "智能匹配",
    16: "智能匹配核心词",
    17: "短语匹配",
    48: "精确匹配",
    127: "分匹配出价",
}

# 质量度三项子分枚举（预估点击率/创意相关性/落地页体验，文档 0299）
QUALITY_SUB_LABELS = {0: "数据积累中", 1: "低于平均", 2: "平均水平", 3: "高于平均"}

MAX_PERIOD_DAYS = 366


def _kw_base_cond(tenant_id: int, keyword_id: int) -> list:
    return [
        KwReportSnapshot.tenant_id == tenant_id,
        KwReportSnapshot.keyword_id == keyword_id,
    ]


async def _period_kpi(
    session: AsyncSession, tenant_id: int, keyword_id: int, start: date, end: date
) -> dict[str, Any]:
    """关键词时段 KPI。avg_rank 口径与 R-14 一致：对快照行做简单平均。"""
    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(KwReportSnapshot.cost), 0),
                func.coalesce(func.sum(KwReportSnapshot.click), 0),
                func.coalesce(func.sum(KwReportSnapshot.impression), 0),
                func.avg(KwReportSnapshot.avg_rank),
                func.coalesce(func.sum(KwReportSnapshot.conversions), 0),
            ).where(
                *_kw_base_cond(tenant_id, keyword_id),
                KwReportSnapshot.report_date >= start,
                KwReportSnapshot.report_date <= end,
            )
        )
    ).one()
    kpi = _derive(_f(row[0]), int(row[1]), int(row[2]), int(row[4]))
    kpi["avg_rank"] = round(float(row[3]), 2) if row[3] is not None else None
    return kpi


def _first_non_null(rows: list, attr: str) -> Any:
    for r in rows:
        v = getattr(r, attr)
        if v is not None:
            return v
    return None


def _category_payload(code: str | None, source: str | None) -> dict[str, Any]:
    return {
        "code": code,
        "label": CATEGORY_LABELS.get(code),
        "source": source,
    }


WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _bid_coefficients(
    base_price: float | None,
    campaign: Campaign | None,
    strategy: PriceStrategy | None,
    adgroup: Adgroup | None = None,
) -> dict[str, Any] | None:
    """出价系数叠加（原型：关键词出价 × 优化排名策略 × 分地域 × 分时段 × 移动比例）。

    5 层全部接入。移动比例 priceRatio：单元级 > 0 时覆盖计划级（≤0=继承计划），
    只作用于移动流量，生效区间下限按 min(1, ratio)、上限按 max(1, ratio) 计；
    维度表还没有该字段数据时（未同步/字段被拒）保留在 missing_layers。
    timeId 编码（文档 0040）：3 位数，首位=星期 1-7，后两位=小时 00-23，
    未设置的小时不投放。
    """
    if campaign is None or base_price is None:
        return None
    sched = campaign.schedule_price_factors or []
    region = campaign.region_price_factor or []
    if not sched and not region:
        return None

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    current_time_id = now.isoweekday() * 100 + now.hour
    current_factor = None
    for s in sched:
        if s.get("timeId") == current_time_id:
            current_factor = s.get("priceFactor")
            break
    sched_factors = [s.get("priceFactor") for s in sched if s.get("priceFactor") is not None]
    region_factors = [r.get("priceFactor") for r in region if r.get("priceFactor") is not None]

    schedule_part = {
        "current_factor": current_factor,  # None = 当前时段未投放
        "current_slot": f"{WEEKDAY_CN[now.isoweekday() - 1]} {now.hour:02d}:00-{(now.hour + 1) % 24:02d}:00",
        "min": min(sched_factors) if sched_factors else None,
        "max": max(sched_factors) if sched_factors else None,
        "entries": len(sched),
    }
    region_part = {
        "min": min(region_factors) if region_factors else None,
        "max": max(region_factors) if region_factors else None,
        "entries": len(region),
    }

    # 优化排名策略层：priceFactor 是加价上限（抢不到目标排名时最多加到 ×factor），
    # 下限按 1.0 计（抢得到就不加价）
    strategy_enabled = (
        strategy is not None
        and strategy.price_factor is not None
        and strategy.is_pause is not True  # isPause: true=关闭（文档语义反直觉）
    )
    ranking_part = {"enabled": strategy_enabled}
    if strategy_enabled:
        ranking_part.update(
            {
                "factor_cap": _f(strategy.price_factor),
                "strategy_name": strategy.strategy_name,
                "target_rank_label": TARGET_RANK_LABELS.get(strategy.target_rank),
            }
        )
    ranking_cap = ranking_part.get("factor_cap", 1.0) if strategy_enabled else 1.0

    # 移动比例层（苏尔寿生产实测语义，2026-06-12）：
    #   单元 -1 = 继承计划；0 = 移动端不投放（仅计算机计划，equipmentType=1）；> 0 = 有效比例
    mobile_ratio = None
    mobile_source = None
    for src, raw in (
        ("adgroup", adgroup.price_ratio if adgroup is not None else None),
        ("campaign", campaign.price_ratio),
    ):
        if raw is None or float(raw) < 0:  # None=没数据 / 负数=继承下一层
            continue
        mobile_ratio = _f(raw)
        mobile_source = src
        break
    mobile_part = {
        "ratio": mobile_ratio,  # None = 数据未同步到，按 1.0 计；0 = 移动端不投放
        "source": mobile_source,  # adgroup=单元级覆盖 / campaign=计划级
    }
    # 只作用于移动流量：区间下限取 min(1, ratio)，上限取 max(1, ratio)。
    # ratio=0 表示移动端无流量，对 PC 端生效出价无影响，两端都按 1.0 计
    if mobile_ratio is not None and mobile_ratio > 0:
        mobile_min = min(1.0, mobile_ratio)
        mobile_max = max(1.0, mobile_ratio)
    else:
        mobile_min = mobile_max = 1.0

    # 整层未配置时按 1.0 计算；但已配时段而当前时段未投放时，
    # current_factor 保持 None，不能误报为正在投放。
    effective_schedule_factor = current_factor if sched else 1.0
    effective_region_factors = region_factors or [1.0]
    effective = None
    if effective_schedule_factor is not None:
        cur_min = round(
            base_price
            * effective_schedule_factor
            * min(effective_region_factors)
            * mobile_min,
            2,
        )
        cur_max = round(
            base_price
            * effective_schedule_factor
            * max(effective_region_factors)
            * ranking_cap
            * mobile_max,
            2,
        )
        effective = {
            "current_min": cur_min,
            "current_max": cur_max,
            # 业务阈值：倍数 > 3 橙色提示，> 4 红色预警（原型规则）
            "max_multiplier": round(
                effective_schedule_factor
                * max(effective_region_factors)
                * ranking_cap
                * mobile_max,
                2,
            ),
        }

    return {
        "base_price": round(base_price, 2),
        "campaign_id": campaign.campaign_id,
        "campaign_name": campaign.campaign_name,
        "ranking_strategy": ranking_part,
        "schedule": schedule_part,
        "region": region_part,
        "mobile": mobile_part,
        "effective": effective,
        "missing_layers": [] if mobile_ratio is not None else ["移动比例"],
    }


def _region_factor_analysis(campaign: Campaign | None) -> dict[str, Any] | None:
    """关键词所属计划的分地域出价系数分析。

    当前系统还没有按地域拆分的效果报表落表；这里展示的是计划设置里的
    regionPriceFactor，用于解释地域层对最终出价的放大/压低。
    """
    if campaign is None:
        return None
    rows = []
    for idx, item in enumerate(campaign.region_price_factor or []):
        if not isinstance(item, dict):
            continue
        factor = item.get("priceFactor")
        if factor is None:
            continue
        region_id = item.get("regionId")
        rows.append(
            {
                "region_id": region_id,
                "region_name": item.get("regionName") or item.get("name") or (f"地域 {region_id}" if region_id is not None else f"地域 {idx + 1}"),
                "price_factor": _f(factor),
            }
        )
    if not rows:
        return {
            "source": "campaign_setting",
            "summary": "未设置分地域出价系数，地域层按 1.0 计。",
            "rows": [],
            "min": 1.0,
            "max": 1.0,
            "avg": 1.0,
        }
    rows.sort(key=lambda x: (x["price_factor"] is None, -(x["price_factor"] or 0)))
    factors = [r["price_factor"] for r in rows if r["price_factor"] is not None]
    return {
        "source": "campaign_setting",
        "summary": f"已设置 {len(rows)} 个地域系数，最高 {max(factors):g}，最低 {min(factors):g}。",
        "rows": rows,
        "min": round(min(factors), 2),
        "max": round(max(factors), 2),
        "avg": round(sum(factors) / len(factors), 2),
    }


def _schedule_factor_analysis(campaign: Campaign | None) -> dict[str, Any] | None:
    """关键词所属计划的分时段出价系数分析。

    schedulePriceFactors 是实际投放小时集合：不设置表示全时段按 1.0；
    设置后，缺失小时视为不投放。
    """
    if campaign is None:
        return None
    factors_by_time: dict[int, float] = {}
    for item in campaign.schedule_price_factors or []:
        if not isinstance(item, dict):
            continue
        time_id = item.get("timeId")
        factor = item.get("priceFactor")
        if time_id is None or factor is None:
            continue
        try:
            factors_by_time[int(time_id)] = _f(factor)
        except (TypeError, ValueError):
            continue

    cells: list[dict[str, Any]] = []
    active_factors: list[float] = []
    if not factors_by_time:
        for weekday in range(1, 8):
            for hour in range(24):
                cells.append(
                    {
                        "weekday": weekday,
                        "weekday_label": WEEKDAY_CN[weekday - 1],
                        "hour": hour,
                        "price_factor": 1.0,
                        "active": True,
                    }
                )
                active_factors.append(1.0)
    else:
        for weekday in range(1, 8):
            for hour in range(24):
                factor = factors_by_time.get(weekday * 100 + hour)
                active = factor is not None
                if active:
                    active_factors.append(factor)
                cells.append(
                    {
                        "weekday": weekday,
                        "weekday_label": WEEKDAY_CN[weekday - 1],
                        "hour": hour,
                        "price_factor": factor,
                        "active": active,
                    }
                )

    active_hours = len(active_factors)
    if active_hours:
        max_factor = max(active_factors)
        min_factor = min(active_factors)
        avg_factor = round(sum(active_factors) / active_hours, 2)
    else:
        max_factor = min_factor = avg_factor = None
    return {
        "source": "campaign_setting",
        "summary": (
            "未设置分时段系数，默认全周 168 小时投放，系数 1.0。"
            if not factors_by_time
            else f"全周 {active_hours} 小时投放，最高系数 {max_factor:g}，最低系数 {min_factor:g}。"
            if active_hours
            else "已设置分时段，但当前没有可投放小时。"
        ),
        "active_hours": active_hours,
        "total_hours": 168,
        "min": min_factor,
        "max": max_factor,
        "avg": avg_factor,
        "cells": cells,
    }


async def _region_performance_analysis(
    session: AsyncSession,
    tenant_id: int,
    keyword_id: int,
    start: date,
    end: date,
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(
                KeywordRegionReport.region_name,
                KeywordRegionReport.region_level,
                func.coalesce(func.sum(KeywordRegionReport.cost), 0),
                func.coalesce(func.sum(KeywordRegionReport.click), 0),
                func.coalesce(func.sum(KeywordRegionReport.impression), 0),
            )
            .where(
                KeywordRegionReport.tenant_id == tenant_id,
                KeywordRegionReport.keyword_id == keyword_id,
                KeywordRegionReport.report_date >= start,
                KeywordRegionReport.report_date <= end,
            )
            .group_by(KeywordRegionReport.region_name, KeywordRegionReport.region_level)
            .order_by(func.sum(KeywordRegionReport.impression).desc())
        )
    ).all()

    out_rows = []
    for name, level, cost, click, impression in rows:
        metrics = _derive(_f(cost), int(click), int(impression))
        out_rows.append(
            {
                "region_name": name,
                "region_level": level,
                **metrics,
            }
        )

    total_cost = sum(r["cost"] for r in out_rows)
    total_click = sum(r["click"] for r in out_rows)
    total_impression = sum(r["impression"] for r in out_rows)
    return {
        "source": "keyword_region_report",
        "metric": "performance",
        "summary": (
            f"已同步 {len(out_rows)} 个地域，展现 {total_impression:,}，点击 {total_click:,}。"
            if out_rows
            else "暂无地域维度效果数据，请先同步关键词地域报告。"
        ),
        "totals": _derive(total_cost, total_click, total_impression),
        "rows": out_rows,
    }


async def _hourly_performance_analysis(
    session: AsyncSession,
    tenant_id: int,
    keyword_id: int,
    start: date,
    end: date,
) -> dict[str, Any]:
    weekday_expr = func.extract("isodow", KeywordHourlyReport.report_datetime)
    rows = (
        await session.execute(
            select(
                weekday_expr.label("weekday"),
                KeywordHourlyReport.hour,
                func.coalesce(func.sum(KeywordHourlyReport.cost), 0),
                func.coalesce(func.sum(KeywordHourlyReport.click), 0),
                func.coalesce(func.sum(KeywordHourlyReport.impression), 0),
            )
            .where(
                KeywordHourlyReport.tenant_id == tenant_id,
                KeywordHourlyReport.keyword_id == keyword_id,
                KeywordHourlyReport.report_date >= start,
                KeywordHourlyReport.report_date <= end,
            )
            .group_by(weekday_expr, KeywordHourlyReport.hour)
        )
    ).all()

    by_slot = {
        (int(weekday), int(hour)): _derive(_f(cost), int(click), int(impression))
        for weekday, hour, cost, click, impression in rows
    }
    cells = []
    for weekday in range(1, 8):
        for hour in range(24):
            metrics = by_slot.get((weekday, hour)) or _derive(0, 0, 0)
            cells.append(
                {
                    "weekday": weekday,
                    "weekday_label": WEEKDAY_CN[weekday - 1],
                    "hour": hour,
                    "active": metrics["impression"] > 0 or metrics["click"] > 0 or metrics["cost"] > 0,
                    **metrics,
                }
            )

    active_cells = [c for c in cells if c["active"]]
    total_cost = sum(c["cost"] for c in active_cells)
    total_click = sum(c["click"] for c in active_cells)
    total_impression = sum(c["impression"] for c in active_cells)
    peak = max((c["impression"] for c in active_cells), default=0)
    return {
        "source": "keyword_hourly_report",
        "metric": "performance",
        "summary": (
            f"已同步 {len(active_cells)} 个有展现时段，展现 {total_impression:,}，点击 {total_click:,}。"
            if active_cells
            else "暂无小时维度效果数据，请先同步关键词小时报告。"
        ),
        "active_hours": len(active_cells),
        "total_hours": 168,
        "peak_impression": peak,
        "totals": _derive(total_cost, total_click, total_impression),
        "cells": cells,
    }


def _campaign_in_schedule_now(campaign: Campaign) -> bool:
    """计划当前时段是否投放。没设置 schedulePriceFactors = 全时段投放；
    设置了但当前 timeId 不在内 = 当前时段不投放（timeId 编码同 _bid_coefficients）。"""
    sched = campaign.schedule_price_factors or []
    if not sched:
        return True
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    current_time_id = now.isoweekday() * 100 + now.hour
    return any(s.get("timeId") == current_time_id for s in sched)


def _serving_payload(
    kw: Keyword, campaign: Campaign | None, adgroup: Adgroup | None
) -> dict[str, Any]:
    """当前时间是否在投：词/单元/计划三层暂停 + 计划分时段。维度数据缺失按在投处理。"""
    if kw.pause is True:
        return {"now": False, "reason": "关键词已暂停"}
    if adgroup is not None and adgroup.pause is True:
        return {"now": False, "reason": "单元已暂停"}
    if campaign is not None and campaign.pause is True:
        return {"now": False, "reason": "计划已暂停"}
    if campaign is not None and not _campaign_in_schedule_now(campaign):
        return {"now": False, "reason": "当前时段不投放"}
    return {"now": True, "reason": "投放中"}


def _peak_multiplier(
    campaign: Campaign | None,
    strategy_cap: float,
    adgroup_ratio: float | None,
) -> float | None:
    """工作台用的"峰值系数乘积"：全周最高时段 × 最高地域 × 策略加价上限 × 移动比例放大端。

    与详情页"当前时段实时值"口径不同——工作台关心的是预警（最坏能放大到几倍），
    用峰值口径筛选结果才稳定（不随查询时刻变化）。
    """
    if campaign is None:
        return None
    sched = campaign.schedule_price_factors or []
    region = campaign.region_price_factor or []
    sched_factors = [s.get("priceFactor") for s in sched if s.get("priceFactor") is not None]
    region_factors = [r.get("priceFactor") for r in region if r.get("priceFactor") is not None]
    if not sched_factors and not region_factors:
        return None
    # 移动比例：单元 -1=继承计划、0=移动不投放（不放大）、>0=有效（取放大端）
    mobile = None
    for raw in (adgroup_ratio, float(campaign.price_ratio) if campaign.price_ratio is not None else None):
        if raw is None or raw < 0:
            continue
        mobile = raw
        break
    return round(
        max(sched_factors or [1.0])
        * max(region_factors or [1.0])
        * strategy_cap
        * (max(1.0, mobile) if mobile else 1.0),
        2,
    )


def _coef_warning(multiplier: float | None) -> str:
    """系数预警分档（原型业务规则）：> 4 红、> 3 橙，其余正常。"""
    if multiplier is None:
        return "normal"
    if multiplier > 4:
        return "red"
    if multiplier > 3:
        return "orange"
    return "normal"


SORTABLE = {
    "impression": Keyword.total_impression,
    "price": Keyword.price,
    "quality": Keyword.quality,
}


@router.get("")
async def list_keywords(
    tenant_id: int = Query(..., description="本地租户 ID"),
    category: str | None = Query(None, description="brand/focus/normal/longtail/new"),
    campaign_id: int | None = Query(None, description="按计划筛选"),
    pause: bool | None = Query(None, description="true=已暂停 false=已启用"),
    serving: bool | None = Query(
        None, description="当前时间是否在投：true=投放中 false=未投（暂停或当前时段不投）"
    ),
    q: str | None = Query(None, description="关键词模糊搜索"),
    coef_warning: str | None = Query(None, description="系数预警档：red/orange/normal"),
    has_suggestion: bool | None = Query(None, description="true=只看有 AI 建议的词"),
    sort_by: str = Query("impression", description="impression/price/quality/clicks_7d/cost_7d"),
    order: str = Query("desc", description="asc/desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """关键词工作台列表：分页 + 筛选 + 7 天指标 + 峰值系数预警。

    7 天窗口锚定该租户最近有数据的日期（苏尔寿 6 月零星投放，锚 today 会全空）。
    """
    # ===== 计划 / 单元维度（算系数乘积 + 名称映射 + 筛选下拉） =====
    campaigns = {
        c.campaign_id: c
        for c in (
            await session.scalars(
                select(Campaign).where(Campaign.tenant_id == tenant_id)
            )
        ).all()
    }
    adgroups = {
        a.adgroup_id: a
        for a in (
            await session.scalars(
                select(Adgroup).where(Adgroup.tenant_id == tenant_id)
            )
        ).all()
    }
    strategies = (
        await session.scalars(
            select(PriceStrategy).where(PriceStrategy.tenant_id == tenant_id)
        )
    ).all()
    strategy_caps: dict[int, float] = {}
    for s in strategies:
        if s.price_factor is None or s.is_pause is True:  # isPause: true=关闭
            continue
        for cid in s.bound_campaign_ids():
            strategy_caps[cid] = float(s.price_factor)

    adgroup_multipliers = {
        a.adgroup_id: _peak_multiplier(
            campaigns.get(a.campaign_id),
            strategy_caps.get(a.campaign_id, 1.0),
            float(a.price_ratio) if a.price_ratio is not None else None,
        )
        for a in adgroups.values()
    }

    # ===== 查询条件 =====
    cond = [Keyword.tenant_id == tenant_id]
    if category == "brand":
        tenant = await session.get(Tenant, tenant_id)
        brand_terms = resolve_brand_terms(tenant) if tenant else []
        brand_parts = [Keyword.category == "brand"]
        brand_parts.extend(Keyword.keyword.ilike(f"%{term}%") for term in brand_terms)
        cond.append(or_(*brand_parts))
    elif category:
        cond.append(Keyword.category == category)
    if campaign_id is not None:
        cond.append(Keyword.campaign_id == campaign_id)
    if pause is not None:
        cond.append(Keyword.pause.is_(pause))
    if serving is not None:
        # 与 _serving_payload 同口径：词/单元/计划暂停 + 计划当前时段。维度缺失按在投
        paused_adg_ids = [a.adgroup_id for a in adgroups.values() if a.pause is True]
        blocked_camp_ids = [
            c.campaign_id
            for c in campaigns.values()
            if c.pause is True or not _campaign_in_schedule_now(c)
        ]
        # IN 对 NULL 列返回 NULL，取反会把无归属的词错误排除——加 NOT NULL 守卫
        not_serving_parts = [Keyword.pause.is_(True)]
        if paused_adg_ids:
            not_serving_parts.append(
                and_(Keyword.adgroup_id.isnot(None), Keyword.adgroup_id.in_(paused_adg_ids))
            )
        if blocked_camp_ids:
            not_serving_parts.append(
                and_(Keyword.campaign_id.isnot(None), Keyword.campaign_id.in_(blocked_camp_ids))
            )
        not_serving = or_(*not_serving_parts)
        cond.append(not_serving if serving is False else ~not_serving)
    if q:
        cond.append(Keyword.keyword.ilike(f"%{q}%"))
    if coef_warning in ("red", "orange", "normal"):
        matched = [
            adg_id
            for adg_id, m in adgroup_multipliers.items()
            if _coef_warning(m) == coef_warning
        ]
        if coef_warning == "normal":
            # 系数数据缺失的词也归"正常"档（无单元归属的同样保留）
            cond.append(
                (Keyword.adgroup_id.in_(matched)) | (Keyword.adgroup_id.is_(None))
                if matched
                else Keyword.adgroup_id.is_(None)
            )
        else:
            if not matched:
                cond.append(Keyword.id == -1)  # 无命中，直接空结果
            else:
                cond.append(Keyword.adgroup_id.in_(matched))
    if has_suggestion is not None:
        sug_subq = select(Suggestion.keyword_id).where(
            Suggestion.tenant_id == tenant_id,
            Suggestion.status == "pending",
            Suggestion.keyword_id.isnot(None),
        )
        cond.append(
            Keyword.keyword_id.in_(sug_subq)
            if has_suggestion
            else Keyword.keyword_id.notin_(sug_subq)
        )

    # ===== 7 天指标子查询（锚定租户最近有数日） =====
    max_date = await session.scalar(
        select(func.max(KwReportSnapshot.report_date)).where(
            KwReportSnapshot.tenant_id == tenant_id
        )
    )
    agg = None
    if max_date is not None:
        agg = (
            select(
                KwReportSnapshot.keyword_id.label("kw_id"),
                func.sum(KwReportSnapshot.click).label("click"),
                func.sum(KwReportSnapshot.cost).label("cost"),
                func.sum(KwReportSnapshot.impression).label("impression"),
                func.avg(KwReportSnapshot.avg_rank).label("avg_rank"),
                func.sum(KwReportSnapshot.conversions).label("conversions"),
            )
            .where(
                KwReportSnapshot.tenant_id == tenant_id,
                KwReportSnapshot.report_date >= max_date - timedelta(days=6),
                KwReportSnapshot.report_date <= max_date,
            )
            .group_by(KwReportSnapshot.keyword_id)
            .subquery()
        )

    # ===== 排序 =====
    if sort_by in SORTABLE:
        sort_col = SORTABLE[sort_by]
    elif sort_by in ("clicks_7d", "cost_7d") and agg is not None:
        sort_col = agg.c.click if sort_by == "clicks_7d" else agg.c.cost
    else:
        sort_col = Keyword.total_impression
    sort_exp = sort_col.asc().nullslast() if order == "asc" else sort_col.desc().nullslast()

    # ===== 总数 + 分页页 =====
    total = await session.scalar(select(func.count()).select_from(Keyword).where(*cond))
    stmt = select(Keyword)
    if agg is not None:
        stmt = select(
            Keyword, agg.c.click, agg.c.cost, agg.c.impression, agg.c.avg_rank, agg.c.conversions
        )
        stmt = stmt.outerjoin(agg, Keyword.keyword_id == agg.c.kw_id)
    stmt = (
        stmt.where(*cond)
        .order_by(sort_exp, Keyword.keyword_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = (await session.execute(stmt)).all()

    # ===== 分类计数（不受分级筛选影响，受其余筛选影响则太绕——保持全量口径） =====
    count_rows = (
        await session.execute(
            select(Keyword.category, func.count())
            .where(Keyword.tenant_id == tenant_id)
            .group_by(Keyword.category)
        )
    ).all()

    # ===== 本页词的 7 天排名走势（工作台 rank-mini 迷你柱） =====
    window_dates: list = []
    rank_trends: dict[int, dict[str, float]] = {}
    if max_date is not None:
        window_dates = [
            (max_date - timedelta(days=offset)).isoformat() for offset in range(6, -1, -1)
        ]
        page_kw_ids = [r[0].keyword_id for r in result]
        if page_kw_ids:
            trend_rows = (
                await session.execute(
                    select(
                        KwReportSnapshot.keyword_id,
                        KwReportSnapshot.report_date,
                        func.avg(KwReportSnapshot.avg_rank),
                    )
                    .where(
                        KwReportSnapshot.tenant_id == tenant_id,
                        KwReportSnapshot.keyword_id.in_(page_kw_ids),
                        KwReportSnapshot.report_date >= max_date - timedelta(days=6),
                        KwReportSnapshot.report_date <= max_date,
                    )
                    .group_by(KwReportSnapshot.keyword_id, KwReportSnapshot.report_date)
                )
            ).all()
            for kw_id, d, rank in trend_rows:
                if rank is not None:
                    rank_trends.setdefault(kw_id, {})[d.isoformat()] = round(float(rank), 2)

    rows = []
    for r in result:
        k: Keyword = r[0]
        click7, cost7, imp7, rank7, conv7 = (
            (r[1], r[2], r[3], r[4], r[5]) if agg is not None else (None, None, None, None, None)
        )
        camp = campaigns.get(k.campaign_id)
        adg = adgroups.get(k.adgroup_id)
        multiplier = adgroup_multipliers.get(k.adgroup_id)
        if multiplier is None and camp is not None:
            multiplier = _peak_multiplier(
                camp, strategy_caps.get(k.campaign_id, 1.0), None
            )
        price = _f(k.price) if k.price is not None else None
        click7 = int(click7) if click7 is not None else None
        cost7 = _f(cost7) if cost7 is not None else None
        imp7 = int(imp7) if imp7 is not None else None
        conv7 = int(conv7) if conv7 is not None else None
        rows.append(
            {
                "keyword_id": k.keyword_id,
                "baidu_account_id": k.baidu_account_id,
                "keyword": k.keyword,
                "category": _category_payload(k.category, k.category_source),
                "campaign_id": k.campaign_id,
                "campaign_name": camp.campaign_name if camp else None,
                "adgroup_id": k.adgroup_id,
                "adgroup_name": adg.adgroup_name if adg else None,
                "match_type": MATCH_TYPE_LABELS.get(k.match_type),
                "price": price,
                "effective": {
                    "multiplier": multiplier,
                    "price": (
                        round(price * multiplier, 2)
                        if price is not None and multiplier is not None
                        else None
                    ),
                    "warning": _coef_warning(multiplier),
                },
                "pause": k.pause,
                "serving": _serving_payload(k, camp, adg),
                "quality": k.quality,
                "total_impression": k.total_impression,
                "metrics_7d": {
                    "click": click7,
                    "cost": cost7,
                    "impression": imp7,
                    "ctr": (
                        round(click7 / imp7 * 100, 2) if click7 is not None and imp7 else None
                    ),
                    "cpc": (
                        round(cost7 / click7, 2) if cost7 is not None and click7 else None
                    ),
                    "avg_rank": round(float(rank7), 2) if rank7 is not None else None,
                    "conversions": conv7,
                    "conv_cost": (
                        round(cost7 / conv7, 2) if cost7 is not None and conv7 else None
                    ),
                },
                "conversions": conv7,  # 词级转化（Detail2 电话点击），转化层接入
                "first_seen_date": (
                    k.first_seen_date.isoformat() if k.first_seen_date else None
                ),
                # 7 天窗口逐日均排（无数据日为 None），前端画 rank-mini 迷你柱
                "rank_trend": [
                    rank_trends.get(k.keyword_id, {}).get(d) for d in window_dates
                ],
            }
        )

    last_synced = await session.scalar(
        select(func.max(Keyword.synced_at)).where(Keyword.tenant_id == tenant_id)
    )

    # ===== 当前在投计数（全量口径，与 _serving_payload 同判定） =====
    sv_paused_adg = [a.adgroup_id for a in adgroups.values() if a.pause is True]
    sv_blocked_camp = [
        c.campaign_id
        for c in campaigns.values()
        if c.pause is True or not _campaign_in_schedule_now(c)
    ]
    sv_parts = [Keyword.pause.is_(True)]
    if sv_paused_adg:
        sv_parts.append(
            and_(Keyword.adgroup_id.isnot(None), Keyword.adgroup_id.in_(sv_paused_adg))
        )
    if sv_blocked_camp:
        sv_parts.append(
            and_(Keyword.campaign_id.isnot(None), Keyword.campaign_id.in_(sv_blocked_camp))
        )
    serving_now_count = await session.scalar(
        select(func.count()).select_from(Keyword).where(
            Keyword.tenant_id == tenant_id, ~or_(*sv_parts)
        )
    )
    now_cn = datetime.now(ZoneInfo("Asia/Shanghai"))

    return {
        "totals": {
            "campaigns": len(campaigns),
            "adgroups": len(adgroups),
            "keywords": await session.scalar(
                select(func.count()).select_from(Keyword).where(Keyword.tenant_id == tenant_id)
            ),
            "serving_now": int(serving_now_count or 0),
            "current_slot": (
                f"{WEEKDAY_CN[now_cn.isoweekday() - 1]} "
                f"{now_cn.hour:02d}:00-{(now_cn.hour + 1) % 24:02d}:00"
            ),
            "last_synced_at": last_synced.isoformat() if last_synced else None,
        },
        "category_counts": {c: int(n) for c, n in count_rows},
        "campaign_options": sorted(
            (
                {"campaign_id": c.campaign_id, "campaign_name": c.campaign_name}
                for c in campaigns.values()
            ),
            key=lambda x: x["campaign_name"] or "",
        ),
        "metrics_window": (
            {
                "start": (max_date - timedelta(days=6)).isoformat(),
                "end": max_date.isoformat(),
            }
            if max_date
            else None
        ),
        "page": page,
        "page_size": page_size,
        "total": int(total or 0),
        "keywords": rows,
    }


EXPORT_MAX_ROWS = 5000


@router.get("/export")
async def export_keywords(
    tenant_id: int = Query(...),
    category: str | None = Query(None),
    campaign_id: int | None = Query(None),
    pause: bool | None = Query(None),
    serving: bool | None = Query(None),
    q: str | None = Query(None),
    coef_warning: str | None = Query(None),
    sort_by: str = Query("impression"),
    order: str = Query("desc"),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """按当前筛选导出 CSV（只读，最多 5000 行）。utf-8-sig 带 BOM，Excel 直接打开不乱码。"""
    data = await list_keywords(
        tenant_id=tenant_id, category=category, campaign_id=campaign_id,
        pause=pause, serving=serving, q=q, coef_warning=coef_warning, sort_by=sort_by,
        order=order, page=1, page_size=EXPORT_MAX_ROWS, session=session,
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "关键词", "分类", "分级来源", "所属计划", "所属单元", "匹配方式",
        "出价", "峰值系数", "生效出价(峰值)", "系数预警", "质量度",
        "7天点击", "7天消费", "7天CTR(%)", "7天CPC", "7天均排",
        "累计展现", "状态", "当前投放", "keyword_id",
    ])
    warning_labels = {"red": "红色", "orange": "橙色", "normal": "正常"}
    for r in data["keywords"]:
        m = r["metrics_7d"]
        writer.writerow([
            r["keyword"], r["category"]["label"] or "未分级",
            "人工" if r["category"]["source"] == "manual" else "自动",
            r["campaign_name"], r["adgroup_name"], r["match_type"],
            r["price"], r["effective"]["multiplier"], r["effective"]["price"],
            warning_labels.get(r["effective"]["warning"], ""), r["quality"],
            m["click"], m["cost"], m["ctr"], m["cpc"], m["avg_rank"],
            r["total_impression"],
            "已暂停" if r["pause"] else "已启用" if r["pause"] is False else "",
            r["serving"]["reason"],
            r["keyword_id"],
        ])
    filename = f"keywords_{tenant_id}_{date.today().isoformat()}.csv"
    return Response(
        content="\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class BatchCategoryRequest(BaseModel):
    tenant_id: int
    keyword_ids: list[int] = Field(..., min_length=1, max_length=500)
    category: str  # brand/focus/normal/longtail/new，auto=恢复自动分级


@router.post("/batch-category")
async def batch_update_category(
    req: BatchCategoryRequest,
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_scoped_auth),
) -> dict:
    """批量改分级（工作台勾选批量操作）。语义与单个接口一致：manual 标记 / auto 恢复重算。"""
    ctx.ensure_tenant(req.tenant_id)
    if req.category != "auto" and req.category not in CATEGORY_LABELS:
        raise HTTPException(400, f"分级只能是 {'/'.join(CATEGORY_LABELS)} 或 auto")

    kws = (
        await session.scalars(
            select(Keyword).where(
                Keyword.tenant_id == req.tenant_id,
                Keyword.keyword_id.in_(req.keyword_ids),
            )
        )
    ).all()
    if not kws:
        raise HTTPException(404, "所选关键词都不在维度表中，请先执行关键词维度同步")

    brand_terms: list[str] = []
    if req.category == "auto":
        tenant = await session.get(Tenant, req.tenant_id)
        brand_terms = resolve_brand_terms(tenant)

    now = datetime.utcnow()
    for kw in kws:
        if req.category == "auto":
            kw.category = classify_one(
                kw.keyword, kw.tabs, kw.total_impression, brand_terms
            )
            kw.category_source = "auto"
        else:
            kw.category = req.category
            kw.category_source = "manual"
        kw.category_updated_at = now
    await session.commit()

    return {
        "status": "ok",
        "updated": len(kws),
        "missing": sorted(set(req.keyword_ids) - {k.keyword_id for k in kws}),
    }


@router.patch("/{keyword_id}/category")
async def update_keyword_category(
    keyword_id: int,
    tenant_id: int = Query(..., description="本地租户 ID"),
    category: str = Query(
        ..., description="brand/focus/normal/longtail/new，传 auto 恢复自动分级"
    ),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """人工改分级（长尾精准词的标记入口）。传 auto 撤销人工标记并立即重算。"""
    if category != "auto" and category not in CATEGORY_LABELS:
        raise HTTPException(400, f"分级只能是 {'/'.join(CATEGORY_LABELS)} 或 auto")

    kw = await session.scalar(
        select(Keyword).where(
            Keyword.tenant_id == tenant_id, Keyword.keyword_id == keyword_id
        )
    )
    if kw is None:
        raise HTTPException(
            404, "该关键词尚未同步到维度表，请先执行关键词维度同步"
        )

    if category == "auto":
        tenant = await session.get(Tenant, tenant_id)
        brand_terms = resolve_brand_terms(tenant)
        kw.category = classify_one(
            kw.keyword, kw.tabs, kw.total_impression, brand_terms
        )
        kw.category_source = "auto"
    else:
        kw.category = category
        kw.category_source = "manual"
    kw.category_updated_at = datetime.utcnow()
    await session.commit()

    return {
        "status": "ok",
        "keyword_id": keyword_id,
        "category": _category_payload(kw.category, kw.category_source),
    }


@router.get("/{keyword_id}")
async def keyword_detail(
    keyword_id: int,
    tenant_id: int = Query(..., description="本地租户 ID"),
    start_date: date | None = Query(None, description="统计起始日期，默认该词首次有数据的日期（全历史，至多 366 天）"),
    end_date: date | None = Query(None, description="统计截止日期，默认该词最近有数据的日期"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """关键词详情：基础信息 + 时段 KPI + 环比 + 日趋势 + 设备维度 + 关联告警。

    苏尔寿 6 月停投，默认时段锚定该词最近有数据的日期，演示无需手动传 5 月区间。
    """
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "租户不存在，请确认 tenant_id")

    # ===== 全期范围 + 维度信息（按最新一天的快照取名称/匹配方式） =====
    span = (
        await session.execute(
            select(
                func.min(KwReportSnapshot.report_date),
                func.max(KwReportSnapshot.report_date),
                func.count(func.distinct(KwReportSnapshot.report_date)),
            ).where(*_kw_base_cond(tenant_id, keyword_id))
        )
    ).one()
    first_date, last_date, active_days = span
    if last_date is None:
        raise HTTPException(404, "该关键词在报告数据中不存在，请确认 keyword_id")

    # 最新一天的快照行（多设备），展现量大的优先，作为基础信息取值来源
    latest_rows = (
        await session.scalars(
            select(KwReportSnapshot)
            .where(
                *_kw_base_cond(tenant_id, keyword_id),
                KwReportSnapshot.report_date == last_date,
            )
            .order_by(KwReportSnapshot.impression.desc())
        )
    ).all()
    keyword_text = _first_non_null(latest_rows, "keyword")
    match_type = _first_non_null(latest_rows, "match_type")
    quality = _first_non_null(latest_rows, "quality_enum")

    # 分级：优先 keywords 维度表（含人工标记）；未同步到的词回退过渡方案
    dim = await session.scalar(
        select(Keyword).where(
            Keyword.tenant_id == tenant_id, Keyword.keyword_id == keyword_id
        )
    )
    if dim is not None:
        category = _category_payload(dim.category, dim.category_source)
    else:
        brand_term = (tenant.name or "").strip()
        is_brand = bool(brand_term) and brand_term.lower() in (keyword_text or "").lower()
        category = _category_payload("brand" if is_brand else None, None)

    # ===== 统计时段（默认覆盖该词全部历史 first_date~last_date，可手动改） =====
    # 历史超 366 天则只默认展示最近 366 天（防御上限，手动仍可在区间内任选）
    end = end_date or last_date
    start = start_date or max(first_date, end - timedelta(days=MAX_PERIOD_DAYS - 1))
    if start > end:
        raise HTTPException(400, "统计起始日期不能晚于截止日期")
    period_days = (end - start).days + 1
    if period_days > MAX_PERIOD_DAYS:
        raise HTTPException(400, f"统计时段最长 {MAX_PERIOD_DAYS} 天")

    # ===== 时段 KPI + 上一等长时段环比 =====
    kpi = await _period_kpi(session, tenant_id, keyword_id, start, end)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=period_days - 1)
    prev_kpi = await _period_kpi(session, tenant_id, keyword_id, prev_start, prev_end)
    kpi_compare = {
        k: {
            "current": kpi[k],
            "previous": prev_kpi[k],
            "change_pct": _change_pct(kpi[k], prev_kpi[k]),
        }
        for k in ("cost", "click", "impression", "cpc", "ctr", "avg_rank", "conversions", "conv_cost")
    }

    # ===== 日趋势（时段内逐日补齐，无数据的日期指标为 0 / 排名为 null） =====
    trend_rows = (
        await session.execute(
            select(
                KwReportSnapshot.report_date,
                func.sum(KwReportSnapshot.cost),
                func.sum(KwReportSnapshot.click),
                func.sum(KwReportSnapshot.impression),
                func.avg(KwReportSnapshot.avg_rank),
            )
            .where(
                *_kw_base_cond(tenant_id, keyword_id),
                KwReportSnapshot.report_date >= start,
                KwReportSnapshot.report_date <= end,
            )
            .group_by(KwReportSnapshot.report_date)
        )
    ).all()
    by_date = {r[0]: r for r in trend_rows}
    trend = []
    for i in range(period_days):
        d = start + timedelta(days=i)
        r = by_date.get(d)
        trend.append(
            {
                "date": d.isoformat(),
                "cost": _f(r[1]) if r else 0.0,
                "click": int(r[2]) if r else 0,
                "impression": int(r[3]) if r else 0,
                "avg_rank": round(float(r[4]), 2) if r and r[4] is not None else None,
            }
        )

    # ===== 历史出价趋势（从该词首次有数据以来，逐日报告出价 bidNew；不限 30 天窗口）=====
    # 出价跨设备一致，按日取 max；只保留有出价记录的日期（出价 0/缺失不画点）。
    bid_trend_rows = (
        await session.execute(
            select(
                KwReportSnapshot.report_date,
                func.max(KwReportSnapshot.bid_new),
            )
            .where(
                *_kw_base_cond(tenant_id, keyword_id),
                KwReportSnapshot.bid_new.isnot(None),
            )
            .group_by(KwReportSnapshot.report_date)
            .order_by(KwReportSnapshot.report_date)
        )
    ).all()
    bid_trend = [
        {"date": d.isoformat(), "bid": _f(b)} for d, b in bid_trend_rows if b is not None
    ]

    # ===== 设备维度 =====
    device_rows = (
        await session.execute(
            select(
                KwReportSnapshot.device,
                func.sum(KwReportSnapshot.cost),
                func.sum(KwReportSnapshot.click),
                func.sum(KwReportSnapshot.impression),
                func.avg(KwReportSnapshot.avg_rank),
            )
            .where(
                *_kw_base_cond(tenant_id, keyword_id),
                KwReportSnapshot.report_date >= start,
                KwReportSnapshot.report_date <= end,
            )
            .group_by(KwReportSnapshot.device)
        )
    ).all()
    device_split = [
        {
            "device": DEVICE_LABELS.get(r[0], "其他"),
            **_derive(_f(r[1]), int(r[2]), int(r[3])),
            "avg_rank": round(float(r[4]), 2) if r[4] is not None else None,
        }
        for r in device_rows
    ]

    # ===== 出价 + 出价系数（分地域/分时段来自计划维度表） =====
    bid_value = None
    if dim is not None and dim.price is not None:
        bid_value = _f(dim.price)
    elif (report_bid := _first_non_null(latest_rows, "bid_new")) is not None:
        bid_value = _f(report_bid)

    camp_id = (dim.campaign_id if dim else None) or _first_non_null(
        latest_rows, "campaign_id"
    )
    adg_id = (dim.adgroup_id if dim else None) or _first_non_null(
        latest_rows, "adgroup_id"
    )
    campaign = None
    strategy = None
    adgroup = None
    if camp_id:
        campaign = await session.scalar(
            select(Campaign).where(
                Campaign.tenant_id == tenant_id, Campaign.campaign_id == camp_id
            )
        )
        # 找绑定到该计划的优化排名策略（账户级策略数量很少，全取后筛）
        strategies = (
            await session.scalars(
                select(PriceStrategy).where(PriceStrategy.tenant_id == tenant_id)
            )
        ).all()
        strategy = next(
            (s for s in strategies if camp_id in s.bound_campaign_ids()), None
        )
    if adg_id:
        adgroup = await session.scalar(
            select(Adgroup).where(
                Adgroup.tenant_id == tenant_id, Adgroup.adgroup_id == adg_id
            )
        )
    bid_coefficients = _bid_coefficients(bid_value, campaign, strategy, adgroup)
    region_analysis = await _region_performance_analysis(session, tenant_id, keyword_id, start, end)
    schedule_analysis = await _hourly_performance_analysis(session, tenant_id, keyword_id, start, end)

    # ===== 关联告警（未处理优先，再按数据日期倒序） =====
    alert_rows = (
        await session.scalars(
            select(Alert)
            .where(Alert.tenant_id == tenant_id, Alert.keyword_id == keyword_id)
            .order_by(Alert.status, Alert.report_date.desc(), Alert.id.desc())
            .limit(20)
        )
    ).all()
    alerts = [
        {
            "id": a.id,
            "priority": a.priority,
            "title": a.title,
            "message": a.message,
            "report_date": a.report_date.isoformat(),
            "metrics": a.metrics or {},
            "status": a.status,
            "detected_at": a.detected_at.isoformat(),
        }
        for a in alert_rows
    ]

    # 触发搜索词：百度搜索词报告不给关键词 ID，只能按触发词名称（trigger_keyword）关联该词
    search_queries = None
    if keyword_text:
        st_rows = (
            await session.scalars(
                select(SearchTermReport)
                .where(
                    SearchTermReport.tenant_id == tenant_id,
                    SearchTermReport.trigger_keyword.ilike(f"%{keyword_text}%"),
                )
                .order_by(SearchTermReport.impression.desc().nulls_last())
                .limit(30)
            )
        ).all()
        if st_rows:
            search_queries = [
                {
                    "query_word": r.query_word,
                    "impression": r.impression,
                    "click": r.click,
                    "cost": float(r.cost) if r.cost is not None else None,
                    "is_added": r.is_added,
                    "status_label": QUERY_STATUS_LABELS.get(r.query_status, "—"),
                }
                for r in st_rows
            ]

    return {
        "tenant": {"id": tenant.id, "name": tenant.name},
        "keyword": {
            "keyword_id": keyword_id,
            "keyword": keyword_text,
            "category": category,
            "pause": dim.pause if dim else None,
            "campaign_id": _first_non_null(latest_rows, "campaign_id"),
            "campaign_name": _first_non_null(latest_rows, "campaign_name"),
            "adgroup_id": _first_non_null(latest_rows, "adgroup_id"),
            "adgroup_name": _first_non_null(latest_rows, "adgroup_name"),
            "match_type": match_type,
            "match_type_label": MATCH_TYPE_LABELS.get(match_type),
            "first_date": first_date.isoformat(),
            "last_date": last_date.isoformat(),
            "active_days": int(active_days),
        },
        "latest": {
            "report_date": last_date.isoformat(),
            # 出价优先用维度表的真实当前出价（getWord price），缺失回退报告 bidNew
            "bid": bid_value,
            "quality": quality,
            "quality_detail": {
                k: {"value": v, "label": QUALITY_SUB_LABELS.get(v)}
                for k, v in (
                    ("预估点击率", _first_non_null(latest_rows, "estimated_click_rate")),
                    ("创意相关性", _first_non_null(latest_rows, "business_relationship")),
                    ("落地页体验", _first_non_null(latest_rows, "land_page_experience")),
                )
            },
            "avg_rank": (
                round(float(_first_non_null(latest_rows, "avg_rank")), 2)
                if _first_non_null(latest_rows, "avg_rank") is not None
                else None
            ),
        },
        "period": {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "days": period_days,
        },
        "kpi": kpi_compare,
        "trend": trend,
        "bid_trend": bid_trend,
        "device_split": device_split,
        "region_analysis": region_analysis,
        "schedule_analysis": schedule_analysis,
        "alerts": alerts,
        "bid_coefficients": bid_coefficients,
        "search_queries": search_queries,
        # 以下区块待后续数据源接入，前端按 null 显示占位说明
        "funnel": None,
        "adjustment_log": None,
    }


# ===== 出价回写（最终执行价 → 百度 updateWord） =====
# 经 dry-run 安全网 + 20% 硬上限 + 台账留痕（app/baidu/writeback.py）。
# 回写的是人工拍板的「最终执行价」，不限于有 AI 建议的词。


class KeywordWritebackRequest(BaseModel):
    tenant_id: int
    price: float = Field(..., gt=0, description="最终执行价（元）")
    approval_id: int | None = None
    confirmation: str | None = None
    idempotency_key: str | None = Field(default=None, min_length=16, max_length=128)


class WritebackBatchItem(BaseModel):
    keyword_id: int
    price: float = Field(..., gt=0)
    approval_id: int | None = None


class WritebackBatchRequest(BaseModel):
    tenant_id: int
    items: list[WritebackBatchItem]


@router.post("/writeback-batch")
async def writeback_batch(
    req: WritebackBatchRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """批量把所选关键词的最终执行价回写百度。逐条经 dry-run 安全网 + 20% 硬上限。

    分桶汇总：applied(真写成功) / simulated(演练) / rejected(校验拒绝) / failed(API 失败)。
    """
    ctx.ensure_tenant(req.tenant_id)
    applied: list[int] = []
    simulated: list[int] = []
    rejected: list[dict] = []
    failed: list[dict] = []
    for it in req.items:
        try:
            rec = await apply_keyword_writeback(
                session, req.tenant_id, it.keyword_id, it.price,
                operator_user_id=ctx.user_id, operator_name=ctx.username,
                approval_id=it.approval_id,
            )
        except WritebackError as e:
            rejected.append({"keyword_id": it.keyword_id, "reason": str(e)})
            continue
        if rec.status == "dry_run":
            simulated.append(it.keyword_id)
        elif rec.status == "success":
            applied.append(it.keyword_id)
        else:
            failed.append({"keyword_id": it.keyword_id, "reason": rec.error_msg})
    return {
        "status": "ok",
        "total": len(req.items),
        "applied": applied,
        "simulated": simulated,
        "rejected": rejected,
        "failed": failed,
    }


class PauseBatchRequest(BaseModel):
    tenant_id: int
    keyword_ids: list[int]
    pause: bool  # True=暂停 False=启用


@router.post("/pause-batch")
async def pause_batch(
    req: PauseBatchRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """批量暂停 / 启用关键词（updateWord pause）。dry-run 保护 + 台账。

    分桶汇总：applied(真写成功) / simulated(演练) / failed(失败)。
    """
    ctx.ensure_tenant(req.tenant_id)
    applied: list[int] = []
    simulated: list[int] = []
    failed: list[dict] = []
    for kid in req.keyword_ids:
        try:
            rec = await apply_pause_writeback(
                session, req.tenant_id, kid, req.pause,
                operator_user_id=ctx.user_id, operator_name=ctx.username,
            )
        except WritebackError as e:
            failed.append({"keyword_id": kid, "reason": str(e)})
            continue
        if rec.status == "dry_run":
            simulated.append(kid)
        elif rec.status == "success":
            applied.append(kid)
        else:
            failed.append({"keyword_id": kid, "reason": rec.error_msg})
    return {
        "status": "ok",
        "total": len(req.keyword_ids),
        "applied": applied,
        "simulated": simulated,
        "failed": failed,
    }


@router.post("/{keyword_id}/writeback")
async def writeback_one(
    keyword_id: int,
    req: KeywordWritebackRequest,
    ctx: AuthContext = Depends(require_scoped_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """把单个关键词的最终执行价回写百度。校验失败返回 400；响应 dry_run 标明是否演练。"""
    from app.api.writeback import wb_to_dict  # 避免顶部跨模块循环

    ctx.ensure_tenant(req.tenant_id)
    try:
        rec = await apply_keyword_writeback(
            session, req.tenant_id, keyword_id, req.price,
            operator_user_id=ctx.user_id, operator_name=ctx.username,
            approval_id=req.approval_id,
            confirmation=req.confirmation,
            idempotency_key=req.idempotency_key,
        )
    except WritebackError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok", "dry_run": rec.dry_run, "writeback": wb_to_dict(rec)}
