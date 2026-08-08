"""AI 投放分析报告（AI 应用路线 ③，客户交付页 / 看板「生成完整报告」按钮目标）。

把自定义日期区间的结构化数据 → 客户能读的分析报告。数据实时聚合，AI 叙述按
(tenant, start_date, end_date) 缓存在 analysis_reports 表。

🚫 红线无关（只读聚合 + 生成文字）。复用调价建议/每日洞察那套 DeepSeek + 缓存 + 降级。
转化/时段/地域/竞品模块依赖未接入的数据源（M2 线索 / 地域时段报告），前端占位。
"""
import calendar
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.deepseek import DeepSeekError, chat_json, is_enabled
from app.models import (
    CATEGORY_LABELS,
    AnalysisReport,
    Alert,
    Keyword,
    KwReportSnapshot,
    MonthlyReport,
    OperationRecord,
    Suggestion,
    Tenant,
)

logger = logging.getLogger(__name__)

KPI_KEYS = ("cost", "click", "impression", "cpc", "ctr")

# 报告模块 key → 中文名（AI 点评按 key 回填；前端 TOC 也用）
MODULE_LABELS = {
    "overview": "整体数据",
    "by_category": "分类报告（按关键词分级）",
    "top_keywords": "TOP10 关键词 · 消费",
    "device": "设备分布",
    "alerts": "异常处置回顾",
    "operations": "优化操作 & 后续计划",
}

SYSTEM_PROMPT = """你是资深 SEM 优化师，为工业品（工业泵 / 分离技术）账户写「投放分析报告」给客户/团队看。
基于给定统计区间的结构化数据，写一份务实、专业、可执行的报告叙述。当前无转化数据，按消费效率 /
流量 / 排名 / 质量度层面分析，不要编造没有的数据（如线索、ROI）。

只返回 JSON（不要多余文字）：
{
  "summary": "3-5 句区间总览摘要，点出该区间投放概况、最值得注意的变化、整体判断",
  "module_comments": {
    "overview": "对整体数据 + 上一等长区间对比的一句点评",
    "by_category": "对各关键词分级表现的点评",
    "top_keywords": "对头部消费词的点评（是否集中、是否健康）",
    "device": "对 PC/移动分布的点评",
    "alerts": "对所选区间异常处置情况的点评",
    "operations": "对所选区间优化操作的点评"
  },
  "next_period_plan": ["3-5 条后续优化计划/建议，每条一句话，具体可落地"]
}"""


async def gather_report_data(
    session: AsyncSession, tenant: Tenant, start: date, end: date
) -> dict:
    """聚合某租户自定义日期区间的全部数据模块（不含 AI）。"""
    # 延迟导入避免循环（app.api.* → reports → 本模块）；复用看板/台账的口径helper
    from app.api.dashboard import DEVICE_LABELS, _change_pct, _derive, _f, _period_kpi
    from app.api.operations import _change

    if start > end:
        raise ValueError("统计起始日期不能晚于截止日期")
    days = (end - start).days + 1

    # ===== 整体 KPI + 上一等长区间对比 =====
    kpi = await _period_kpi(session, tenant.id, start, end)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    prev_kpi = await _period_kpi(session, tenant.id, prev_start, prev_end)
    kpi_compare = {
        k: {
            "current": kpi[k],
            "previous": prev_kpi[k],
            "change_pct": _change_pct(kpi[k], prev_kpi[k]),
        }
        for k in KPI_KEYS
    }

    # 投放天数（有消费的天）
    active_days = await session.scalar(
        select(func.count(func.distinct(KwReportSnapshot.report_date))).where(
            KwReportSnapshot.tenant_id == tenant.id,
            KwReportSnapshot.report_date >= start,
            KwReportSnapshot.report_date <= end,
            KwReportSnapshot.cost > 0,
        )
    )

    # ===== 所选区间消费 / 月预算参考 =====
    monthly_budget = _f(tenant.monthly_budget) if tenant.monthly_budget else None
    budget = {
        "monthly_budget": monthly_budget,
        "month_cost": kpi["cost"],  # 兼容旧前端字段名，实际为所选区间消费
        "period_cost": kpi["cost"],
        "usage_pct": (round(kpi["cost"] / monthly_budget * 100, 1) if monthly_budget else None),
    }

    # ===== 日趋势 =====
    trend_rows = (
        await session.execute(
            select(
                KwReportSnapshot.report_date,
                func.sum(KwReportSnapshot.cost),
                func.sum(KwReportSnapshot.click),
                func.sum(KwReportSnapshot.impression),
            )
            .where(
                KwReportSnapshot.tenant_id == tenant.id,
                KwReportSnapshot.report_date >= start,
                KwReportSnapshot.report_date <= end,
            )
            .group_by(KwReportSnapshot.report_date)
        )
    ).all()
    # 补满所选区间每一天（没数据的天补 0），趋势才读得出哪些天在投，
    # 否则只投几天时柱子太少、被前端拉成大色块
    by_day = {r[0]: r for r in trend_rows}
    trend = []
    cur = start
    while cur <= end:
        r = by_day.get(cur)
        trend.append({
            "date": cur.isoformat(),
            "cost": _f(r[1]) if r else 0.0,
            "click": int(r[2]) if r else 0,
            "impression": int(r[3]) if r else 0,
        })
        cur += timedelta(days=1)

    # ===== 分类报告（按关键词 5 分级；产品线分组规则未定，用分级替代） =====
    cat_rows = (
        await session.execute(
            select(
                Keyword.category,
                func.sum(KwReportSnapshot.cost),
                func.sum(KwReportSnapshot.click),
                func.sum(KwReportSnapshot.impression),
            )
            .select_from(KwReportSnapshot)
            .outerjoin(
                Keyword,
                and_(
                    Keyword.tenant_id == KwReportSnapshot.tenant_id,
                    Keyword.keyword_id == KwReportSnapshot.keyword_id,
                ),
            )
            .where(
                KwReportSnapshot.tenant_id == tenant.id,
                KwReportSnapshot.report_date >= start,
                KwReportSnapshot.report_date <= end,
            )
            .group_by(Keyword.category)
        )
    ).all()
    total_cat_cost = sum(_f(r[1]) for r in cat_rows) or None
    by_category = sorted(
        [
            {
                "category": r[0] or "uncategorized",
                "category_label": CATEGORY_LABELS.get(r[0], "未分类"),
                **_derive(_f(r[1]), int(r[2]), int(r[3])),
                "cost_share_pct": (
                    round(_f(r[1]) / total_cat_cost * 100, 1) if total_cat_cost else None
                ),
            }
            for r in cat_rows
        ],
        key=lambda x: x["cost"],
        reverse=True,
    )

    # ===== TOP10 消费关键词 =====
    kw_rows = (
        await session.execute(
            select(
                KwReportSnapshot.keyword_id,
                func.max(KwReportSnapshot.keyword),
                func.sum(KwReportSnapshot.cost),
                func.sum(KwReportSnapshot.click),
                func.sum(KwReportSnapshot.impression),
                func.avg(KwReportSnapshot.avg_rank),
            )
            .where(
                KwReportSnapshot.tenant_id == tenant.id,
                KwReportSnapshot.report_date >= start,
                KwReportSnapshot.report_date <= end,
                KwReportSnapshot.keyword_id.isnot(None),
            )
            .group_by(KwReportSnapshot.keyword_id)
            .order_by(func.sum(KwReportSnapshot.cost).desc())
            .limit(10)
        )
    ).all()
    top_keywords = [
        {
            "keyword_id": r[0],
            "keyword": r[1],
            **_derive(_f(r[2]), int(r[3]), int(r[4])),
            "avg_rank": round(float(r[5]), 1) if r[5] is not None else None,
        }
        for r in kw_rows
    ]

    # ===== 设备分布 =====
    dev_rows = (
        await session.execute(
            select(
                KwReportSnapshot.device,
                func.sum(KwReportSnapshot.cost),
                func.sum(KwReportSnapshot.click),
                func.sum(KwReportSnapshot.impression),
            )
            .where(
                KwReportSnapshot.tenant_id == tenant.id,
                KwReportSnapshot.report_date >= start,
                KwReportSnapshot.report_date <= end,
            )
            .group_by(KwReportSnapshot.device)
        )
    ).all()
    total_dev_cost = sum(_f(r[1]) for r in dev_rows) or None
    device_split = [
        {
            "device": DEVICE_LABELS.get(r[0], "其他"),
            **_derive(_f(r[1]), int(r[2]), int(r[3])),
            "cost_share_pct": (
                round(_f(r[1]) / total_dev_cost * 100, 1) if total_dev_cost else None
            ),
        }
        for r in dev_rows
    ]

    # ===== 异常处置回顾（所选区间告警，按状态计数） =====
    alert_rows = (
        await session.execute(
            select(Alert.status, func.count())
            .where(
                Alert.tenant_id == tenant.id,
                Alert.report_date >= start,
                Alert.report_date <= end,
            )
            .group_by(Alert.status)
        )
    ).all()
    alerts_review = {s: int(n) for s, n in alert_rows}

    # ===== 所选区间优化操作统计（调价台账）+ AI 建议采纳数 =====
    start_dt = datetime.combine(start, datetime.min.time())
    end_exclusive = datetime.combine(end + timedelta(days=1), datetime.min.time())
    op_rows = (
        await session.scalars(
            select(OperationRecord).where(
                OperationRecord.tenant_id == tenant.id,
                OperationRecord.opt_time >= start_dt,
                OperationRecord.opt_time < end_exclusive,
            )
        )
    ).all()
    op_by_level: dict[str, int] = {}
    over_limit = 0
    for r in op_rows:
        lvl = {5: "关键词", 1: "单元", 2: "计划"}.get(r.opt_level, "其他")
        op_by_level[lvl] = op_by_level.get(lvl, 0) + 1
        c = _change(r.old_value, r.new_value)
        if c and c["over_limit"]:
            over_limit += 1
    adopted = await session.scalar(
        select(func.count()).select_from(Suggestion).where(
            Suggestion.tenant_id == tenant.id,
            Suggestion.status == "adopted",
            Suggestion.adopted_at >= start_dt,
            Suggestion.adopted_at < end_exclusive,
        )
    )
    operations = {
        "total": len(op_rows),
        "by_level": op_by_level,
        "over_limit": over_limit,
        "ai_suggestions_adopted": int(adopted or 0),
    }

    return {
        "tenant": {"id": tenant.id, "name": tenant.name, "strategy": tenant.strategy},
        "period": {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "days": days,
            "active_days": int(active_days or 0),
        },
        "kpi": kpi_compare,
        "budget": budget,
        "trend": trend,
        "by_category": by_category,
        "top_keywords": top_keywords,
        "device_split": device_split,
        "alerts_review": alerts_review,
        "operations": operations,
        # 依赖未接入数据源的模块，前端占位（保持原型 11 模块的完整框架）
        "pending_modules": {
            "conversion": "转化数据待 M2 爱番番线索接入",
            "hourly": "时段绩效报告未同步",
            "region": "地域绩效报告未同步",
            "competitor": "竞品监控无数据源（内部人工补充）",
        },
    }


def _build_prompt(data: dict) -> str:
    p = data["period"]
    k = data["kpi"]
    lines = [
        f"客户：{data['tenant']['name']}",
        f"统计区间：{p['start_date']}~{p['end_date']}（投放 {p['active_days']}/{p['days']} 天）",
        "",
        "【整体数据（括号内为上一等长区间对比）】",
        f"消费 ¥{k['cost']['current']}（{_pct(k['cost']['change_pct'])}），"
        f"点击 {k['click']['current']}（{_pct(k['click']['change_pct'])}），"
        f"展现 {k['impression']['current']}（{_pct(k['impression']['change_pct'])}）",
        f"平均点击成本 ¥{k['cpc']['current']}（{_pct(k['cpc']['change_pct'])}），"
        f"点击率 {_ctr(k['ctr']['current'])}（{_pct(k['ctr']['change_pct'])}）",
    ]
    b = data["budget"]
    if b["monthly_budget"]:
        lines.append(
            f"所选区间消费 ¥{b['period_cost']}，月预算参考 ¥{b['monthly_budget']}，"
            f"区间消费相当于月预算的 {b['usage_pct']}%"
        )

    if data["by_category"]:
        lines.append("\n【分类报告（按关键词分级，消费占比）】")
        for c in data["by_category"]:
            lines.append(
                f"  {c['category_label']}：消费 ¥{c['cost']}（{c['cost_share_pct']}%），"
                f"点击 {c['click']}，点击率 {_ctr(c['ctr'])}"
            )

    if data["top_keywords"]:
        lines.append("\n【TOP 消费关键词】")
        for i, c in enumerate(data["top_keywords"][:5], 1):
            lines.append(
                f"  {i}. {c['keyword']}：消费 ¥{c['cost']}，点击 {c['click']}，"
                f"点击率 {_ctr(c['ctr'])}，均排名 {c['avg_rank']}"
            )

    if data["device_split"]:
        dev = "；".join(
            f"{d['device']} 消费 ¥{d['cost']}（{d['cost_share_pct']}%）点击率 {_ctr(d['ctr'])}"
            for d in data["device_split"]
        )
        lines.append(f"\n【设备分布】{dev}")

    a = data["alerts_review"]
    if a:
        lines.append(
            "\n【异常处置】"
            + "，".join(f"{s} {n}" for s, n in a.items())
            + "（open=未处理 resolved=已处理 merged=已归并）"
        )

    o = data["operations"]
    lines.append(
        f"\n【所选区间优化操作】共 {o['total']} 次"
        + (f"（{('，'.join(f'{k}{v}' for k, v in o['by_level'].items()))}）" if o["by_level"] else "")
        + f"，其中超 20% 上限 {o['over_limit']} 次；AI 建议采纳 {o['ai_suggestions_adopted']} 条"
    )
    return "\n".join(lines)


def _pct(v) -> str:
    if v is None:
        return "上一等长区间无可比数据"
    return f"较上一等长区间{'+' if v >= 0 else ''}{v}%"


def _ctr(v) -> str:
    return f"{round(v * 100, 2)}%" if v is not None else "—"


async def generate_narrative(data: dict) -> dict | None:
    """对结构化区间数据生成 AI 叙述。未配 key 返回 None；失败抛 DeepSeekError。"""
    if not is_enabled():
        return None
    out = await chat_json(SYSTEM_PROMPT, _build_prompt(data))
    return {
        "summary": str(out.get("summary") or ""),
        "module_comments": out.get("module_comments") or {},
        "next_period_plan": out.get("next_period_plan") or [],
    }


async def get_analysis_report(
    session: AsyncSession,
    tenant: Tenant,
    start: date,
    end: date,
    force: bool = False,
) -> dict:
    """组装自定义日期区间报告，并按租户+区间缓存 AI 叙述。"""
    data = await gather_report_data(session, tenant, start, end)
    cached = await session.scalar(
        select(AnalysisReport).where(
            AnalysisReport.tenant_id == tenant.id,
            AnalysisReport.start_date == start,
            AnalysisReport.end_date == end,
        )
    )
    narrative = None
    generated_at = None
    if cached and not force:
        narrative = {
            "summary": cached.summary or "",
            "module_comments": (cached.narrative or {}).get("module_comments", {}),
            "next_period_plan": (cached.narrative or {}).get(
                "next_period_plan", []
            ),
        }
        generated_at = cached.generated_at
    elif is_enabled():
        try:
            narrative = await generate_narrative(data)
        except DeepSeekError as exc:
            logger.warning(
                "区间报告叙述生成失败 tenant=%s %s~%s：%s",
                tenant.id,
                start,
                end,
                exc,
            )
        if narrative is not None:
            now = datetime.utcnow()
            payload = {
                "module_comments": narrative["module_comments"],
                "next_period_plan": narrative["next_period_plan"],
            }
            if cached:
                cached.summary = narrative["summary"]
                cached.narrative = payload
                cached.model = "deepseek-chat"
                cached.generated_at = now
            else:
                session.add(
                    AnalysisReport(
                        tenant_id=tenant.id,
                        start_date=start,
                        end_date=end,
                        summary=narrative["summary"],
                        narrative=payload,
                        model="deepseek-chat",
                        generated_at=now,
                    )
                )
            await session.commit()
            generated_at = now

    return {
        "ai_enabled": is_enabled(),
        "module_labels": MODULE_LABELS,
        "data": data,
        "narrative": narrative,
        "generated_at": generated_at.isoformat() if generated_at else None,
    }


async def get_monthly_report(
    session: AsyncSession,
    tenant: Tenant,
    year: int,
    month: int,
    force: bool = False,
) -> dict:
    """组装月报：实时数据模块 + 缓存/新生成的 AI 叙述。

    数据模块永远返回（不依赖 AI）。AI 叙述：缓存命中直接用；未命中且配了 key 才生成；
    未配 key / 生成失败 → narrative=null（前端只是不显示 AI 文字，报告照出）。
    """
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    data = await gather_report_data(session, tenant, start, end)
    data["period"].update({"year": year, "month": month})

    cached = await session.scalar(
        select(MonthlyReport).where(
            MonthlyReport.tenant_id == tenant.id,
            MonthlyReport.year == year,
            MonthlyReport.month == month,
        )
    )
    narrative = None
    generated_at = None
    if cached and not force:
        narrative = {
            "summary": cached.summary or "",
            "module_comments": (cached.narrative or {}).get("module_comments", {}),
            "next_period_plan": (cached.narrative or {}).get(
                "next_month_plan", []
            ),
        }
        generated_at = cached.generated_at
    elif is_enabled():
        try:
            narrative = await generate_narrative(data)
        except DeepSeekError as e:
            logger.warning("月报叙述生成失败 tenant=%s %s-%s：%s", tenant.id, year, month, e)
            narrative = None
        if narrative is not None:
            now = datetime.utcnow()
            if cached:
                cached.summary = narrative["summary"]
                cached.narrative = {
                    "module_comments": narrative["module_comments"],
                    "next_month_plan": narrative["next_period_plan"],
                }
                cached.model = "deepseek-chat"
                cached.generated_at = now
            else:
                cached = MonthlyReport(
                    tenant_id=tenant.id, year=year, month=month,
                    summary=narrative["summary"],
                    narrative={
                        "module_comments": narrative["module_comments"],
                        "next_month_plan": narrative["next_period_plan"],
                    },
                    model="deepseek-chat", generated_at=now,
                )
                session.add(cached)
            await session.commit()
            generated_at = now

    return {
        "ai_enabled": is_enabled(),
        "module_labels": MODULE_LABELS,
        "data": data,
        "narrative": narrative,
        "generated_at": generated_at.isoformat() if generated_at else None,
    }
