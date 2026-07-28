"""AI 每日洞察生成。

基于当月至今 KPI + 设备分布 + 待处理告警 + 百度官方波动归因，DeepSeek 生成「今日要点」。
按 (tenant, date) 缓存（daily_insights 表）；未配 key 返回 None（盯盘不显示洞察）。
波动归因（文档 1033）洞察生成时实时拉取，百度失败/未授权时静默降级为无归因洞察。
"""
import asyncio
import logging
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.deepseek import DeepSeekError, chat_json, is_enabled
from app.api.dashboard import DEVICE_LABELS, _period_kpi
from app.baidu.services.diagnosis import DIMENSION_LABELS, FluctuationService
from app.models import Alert, BaiduAccount, Campaign, DailyInsight, KwReportSnapshot, Tenant

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是资深 SEM 优化师，为工业品（工业泵 / 分离技术）账户写「每日盯盘洞察」。
基于给你的近期数据 + 待处理告警，输出运营一眼能抓住重点的洞察。
务实、具体、给可执行动作；当前无转化数据，按流量 / 排名层判断，不要编造没有的数据。
若数据里有「百度官方波动归因」，它是百度官方对涨跌原因的判定，优先据此解释数据变化
（提炼成结论写进 highlights，不要照抄原文），并让 actions 针对归因对症下药。

只返回 JSON（不要多余文字）：
{
  "summary": "1-2 句今日总体要点",
  "highlights": ["2-4 条关键发现，每条一句话"],
  "actions": ["2-3 条今日建议动作，每条一句话"]
}"""

# 每计划拉的波动指标；转化(4)苏尔寿口径数据少，出结果也照喂
_FLUX_DIMENSIONS = (1, 2, 3, 4)
_FLUX_MAX_CAMPAIGNS = 8  # 防多计划账户把洞察生成拖太久


def _format_flux_factor(factor: dict) -> dict:
    """百度 factor → 精简条目（存 detail + 喂 prompt 共用）。"""
    top = [
        f"{k.get('keyword')}({k.get('changeValue')})"
        for k in (factor.get("topKeywords") or [])
        if isinstance(k, dict) and k.get("keyword")
    ]
    return {"reason": str(factor.get("description") or ""), "top_keywords": top[:5]}


async def _gather_fluctuations(
    session: AsyncSession, tenant: Tenant, target_date: date
) -> list[dict]:
    """拉各在投计划的百度官方波动归因（日环比）。未授权/接口失败返回空列表。"""
    from app.baidu.sync import _account_client  # 函数内 import，避免模块加载环

    acc = await session.scalar(
        select(BaiduAccount).where(
            BaiduAccount.tenant_id == tenant.id, BaiduAccount.status == "active"
        )
    )
    if acc is None:
        return []
    campaigns = (
        (
            await session.execute(
                select(Campaign.campaign_id, Campaign.campaign_name)
                .where(Campaign.tenant_id == tenant.id, Campaign.pause.is_not(True))
                .limit(_FLUX_MAX_CAMPAIGNS)
            )
        )
        .all()
    )
    if not campaigns:
        return []

    svc = FluctuationService(_account_client(acc))
    diagnosis_date = target_date.strftime("%Y%m%d")

    async def _one(camp_id: int, dim: int):
        try:
            return await svc.query_fluctuation_reasons(camp_id, diagnosis_date, dim)
        except Exception as e:  # noqa: BLE001  单点失败不拖垮整份洞察
            logger.debug("波动归因失败 campaign=%s dim=%s：%s", camp_id, dim, e)
            return []

    tasks = [(cid, name, dim) for cid, name in campaigns for dim in _FLUX_DIMENSIONS]
    factor_lists = await asyncio.gather(*(_one(cid, dim) for cid, _, dim in tasks))

    entries: list[dict] = []
    for (cid, name, dim), factors in zip(tasks, factor_lists):
        items = [f for f in map(_format_flux_factor, factors) if f["reason"]]
        if items:
            entries.append(
                {
                    "campaign": name or str(cid),
                    "dimension": DIMENSION_LABELS.get(dim, str(dim)),
                    "factors": items,
                }
            )
    return entries


async def _gather(session: AsyncSession, tenant: Tenant, target_date: date):
    month_start = target_date.replace(day=1)
    kpi = await _period_kpi(session, tenant.id, month_start, target_date)
    alerts = (
        await session.execute(
            select(Alert.priority, Alert.title, Alert.keyword)
            .where(Alert.tenant_id == tenant.id, Alert.status == "open")
            .order_by(Alert.priority)
            .limit(20)
        )
    ).all()
    dev = (
        await session.execute(
            select(KwReportSnapshot.device, func.sum(KwReportSnapshot.cost))
            .where(
                KwReportSnapshot.tenant_id == tenant.id,
                KwReportSnapshot.report_date >= month_start,
                KwReportSnapshot.report_date <= target_date,
            )
            .group_by(KwReportSnapshot.device)
        )
    ).all()
    flux = await _gather_fluctuations(session, tenant, target_date)
    return month_start, kpi, alerts, dev, flux


def _build_prompt(tenant, target_date, month_start, kpi, alerts, dev, flux) -> str:
    lines = [
        f"客户：{tenant.name}",
        f"统计区间：{month_start} ~ {target_date}（本月至今）",
        f"消费 ¥{kpi['cost']}，点击 {kpi['click']}，展现 {kpi['impression']}，"
        f"平均点击成本(CPC) ¥{kpi['cpc']}，点击率(CTR) {kpi['ctr']}",
    ]
    if dev:
        dev_str = "、".join(
            f"{DEVICE_LABELS.get(d, '其他')} ¥{float(c or 0):.0f}" for d, c in dev
        )
        lines.append(f"分设备消费：{dev_str}")
    if alerts:
        lines.append("待处理告警：")
        for p, t, kw in alerts:
            lines.append(f"  [{p}] {t}" + (f"（关键词：{kw}）" if kw else ""))
    else:
        lines.append("当前无待处理告警。")
    if flux:
        lines.append(f"百度官方波动归因（{target_date} 对比前一日）：")
        for e in flux:
            for f in e["factors"]:
                kw_str = f"（涉及词：{'、'.join(f['top_keywords'])}）" if f["top_keywords"] else ""
                lines.append(f"  [{e['campaign']}·{e['dimension']}] {f['reason']}{kw_str}")
    return "\n".join(lines)


async def generate_insight(
    session: AsyncSession,
    tenant: Tenant,
    target_date: date | None = None,
    force: bool = False,
) -> DailyInsight | None:
    """生成或取缓存某租户某天的洞察。未配 key 返回 None；AI 失败返回旧缓存（若有）。"""
    if not is_enabled():
        return None
    if target_date is None:
        target_date = await session.scalar(
            select(func.max(KwReportSnapshot.report_date)).where(
                KwReportSnapshot.tenant_id == tenant.id
            )
        )
    if target_date is None:
        return None

    existing = await session.scalar(
        select(DailyInsight).where(
            DailyInsight.tenant_id == tenant.id,
            DailyInsight.insight_date == target_date,
        )
    )
    if existing and not force:
        return existing

    month_start, kpi, alerts, dev, flux = await _gather(session, tenant, target_date)
    try:
        out = await chat_json(
            SYSTEM_PROMPT,
            _build_prompt(tenant, target_date, month_start, kpi, alerts, dev, flux),
        )
    except DeepSeekError as e:
        logger.warning("每日洞察生成失败 tenant=%s：%s", tenant.id, e)
        return existing

    summary = str(out.get("summary") or "")
    detail = {
        "highlights": out.get("highlights", []),
        "actions": out.get("actions", []),
        "fluctuations": flux,  # 原始归因随洞察落库，前端展开显示
    }
    if existing:
        existing.summary = summary
        existing.detail = detail
        existing.model = "deepseek-chat"
    else:
        existing = DailyInsight(
            tenant_id=tenant.id,
            insight_date=target_date,
            summary=summary,
            detail=detail,
            model="deepseek-chat",
        )
        session.add(existing)
    await session.commit()
    return existing
