"""客户画像（喂 AI 调价建议 + 画像展示页）。

把一个客户的现有数据聚合成 6 维画像：基础定位 / 账户结构 / 出价习惯 / 效果水位 /
调价行为 / AI 建议采纳偏好。两用途：
  - `profile_brief()`：压成一段中文喂进调价建议 judge 的 prompt，让 AI「懂这个客户」。
  - `gather_profile()` + `generate_summary()`：画像页展示结构化数据 + AI 总结（缓存在 tenants）。

全部只读聚合现有数据，不碰百度写回红线。复用调价建议/月报那套 DeepSeek + 降级。
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.deepseek import DeepSeekError, chat_json, is_enabled
from app.models import (
    CATEGORY_LABELS,
    Adgroup,
    Campaign,
    Keyword,
    KwReportSnapshot,
    OperationRecord,
    Suggestion,
    Tenant,
)

logger = logging.getLogger(__name__)

PERF_DAYS = 30
ADJ_DAYS = 90


def _ratio(a, b):
    return round(a / b * 100, 1) if b else None


async def gather_profile(session: AsyncSession, tenant: Tenant) -> dict:
    """聚合某客户的 6 维画像（实时，不含 AI 总结）。"""
    from app.api.dashboard import DEVICE_LABELS, _derive, _f
    from app.api.operations import _change

    tid = tenant.id

    # ① 基础定位
    basics = {
        "name": tenant.name,
        "industry": tenant.industry or "（未填）",
        "business_desc": tenant.business_desc or "",
        "brand_terms": tenant.brand_terms or [tenant.name],
        "strategy": tenant.strategy,
        "monthly_budget": _f(tenant.monthly_budget) if tenant.monthly_budget else None,
    }

    # ② 账户结构
    n_campaign = await session.scalar(
        select(func.count()).select_from(Campaign).where(Campaign.tenant_id == tid)
    )
    n_adgroup = await session.scalar(
        select(func.count()).select_from(Adgroup).where(Adgroup.tenant_id == tid)
    )
    cat_rows = (
        await session.execute(
            select(Keyword.category, func.count())
            .where(Keyword.tenant_id == tid)
            .group_by(Keyword.category)
        )
    ).all()
    cat_dist = {(c or "uncategorized"): int(n) for c, n in cat_rows}
    structure = {
        "campaigns": int(n_campaign or 0),
        "adgroups": int(n_adgroup or 0),
        "keywords": sum(cat_dist.values()),
        "category_dist": [
            {"category": c, "label": CATEGORY_LABELS.get(c, "未分类"), "count": n}
            for c, n in sorted(cat_dist.items(), key=lambda x: -x[1])
        ],
    }

    # ③ 出价习惯：分级均价 + 出价 vs 百度指导价偏离
    bid_rows = (
        await session.execute(
            select(
                Keyword.category,
                func.avg(Keyword.price),
                func.count(),
            )
            .where(Keyword.tenant_id == tid, Keyword.price.isnot(None), Keyword.pause.isnot(True))
            .group_by(Keyword.category)
        )
    ).all()
    avg_price_by_cat = [
        {"label": CATEGORY_LABELS.get(c, "未分类"), "avg_price": round(float(p), 2)}
        for c, p, n in bid_rows if p is not None
    ]
    # 出价 vs 指导价（计算机指导价 left_price_guide）
    dev_row = (
        await session.execute(
            select(
                func.avg(Keyword.price - Keyword.left_price_guide),
                func.count(),
                func.count().filter(Keyword.price > Keyword.left_price_guide),
            ).where(
                Keyword.tenant_id == tid,
                Keyword.price.isnot(None),
                Keyword.left_price_guide.isnot(None),
                Keyword.pause.isnot(True),
            )
        )
    ).one()
    guide_n = int(dev_row[1] or 0)
    bid_habits = {
        "avg_price_by_category": avg_price_by_cat,
        "guide_compare_count": guide_n,
        "avg_diff_vs_guide": round(float(dev_row[0]), 2) if dev_row[0] is not None else None,
        "above_guide_pct": _ratio(int(dev_row[2] or 0), guide_n),
    }

    # ④ 效果水位：近 PERF_DAYS 天（锚定最近有数日）+ 设备占比 + 质量度
    latest = await session.scalar(
        select(func.max(KwReportSnapshot.report_date)).where(KwReportSnapshot.tenant_id == tid)
    )
    performance = {"window": None, "kpi": None, "device_split": [], "avg_quality": None}
    if latest is not None:
        start = latest - timedelta(days=PERF_DAYS - 1)
        row = (
            await session.execute(
                select(
                    func.coalesce(func.sum(KwReportSnapshot.cost), 0),
                    func.coalesce(func.sum(KwReportSnapshot.click), 0),
                    func.coalesce(func.sum(KwReportSnapshot.impression), 0),
                    func.avg(KwReportSnapshot.avg_rank),
                ).where(
                    KwReportSnapshot.tenant_id == tid,
                    KwReportSnapshot.report_date >= start,
                    KwReportSnapshot.report_date <= latest,
                )
            )
        ).one()
        kpi = _derive(_f(row[0]), int(row[1]), int(row[2]))
        kpi["avg_rank"] = round(float(row[3]), 2) if row[3] is not None else None
        dev_rows = (
            await session.execute(
                select(KwReportSnapshot.device, func.sum(KwReportSnapshot.cost))
                .where(
                    KwReportSnapshot.tenant_id == tid,
                    KwReportSnapshot.report_date >= start,
                    KwReportSnapshot.report_date <= latest,
                )
                .group_by(KwReportSnapshot.device)
            )
        ).all()
        tot = sum(_f(c) for _, c in dev_rows) or None
        performance = {
            "window": {"start": start.isoformat(), "end": latest.isoformat()},
            "kpi": kpi,
            "device_split": [
                {"device": DEVICE_LABELS.get(d, "其他"), "cost": _f(c), "cost_share_pct": _ratio(_f(c), tot)}
                for d, c in dev_rows
            ],
            "avg_quality": round(
                float(await session.scalar(
                    select(func.avg(Keyword.quality)).where(
                        Keyword.tenant_id == tid, Keyword.quality.isnot(None)
                    )
                ) or 0), 1
            ) or None,
        }

    # ⑤ 调价行为（近 ADJ_DAYS 天，关键词级出价改动）
    since = datetime.utcnow() - timedelta(days=ADJ_DAYS)
    op_rows = (
        await session.scalars(
            select(OperationRecord).where(
                OperationRecord.tenant_id == tid,
                OperationRecord.opt_time >= since,
                OperationRecord.opt_level == 5,
            )
        )
    ).all()
    raise_n = lower_n = over_n = 0
    pcts = []
    for r in op_rows:
        c = _change(r.old_value, r.new_value)
        if not c:
            continue
        pcts.append(abs(c["pct"]))
        if c["over_limit"]:
            over_n += 1
        if c["pct"] > 0:
            raise_n += 1
        elif c["pct"] < 0:
            lower_n += 1
    adjust_behavior = {
        "window_days": ADJ_DAYS,
        "total": len(op_rows),
        "avg_abs_pct": round(sum(pcts) / len(pcts), 1) if pcts else None,
        "over_limit": over_n,
        "raise_count": raise_n,
        "lower_count": lower_n,
    }

    # ⑥ AI 建议采纳偏好
    sug_rows = (
        await session.execute(
            select(Suggestion.status, func.count())
            .where(Suggestion.tenant_id == tid)
            .group_by(Suggestion.status)
        )
    ).all()
    sug_cnt = {s: int(n) for s, n in sug_rows}
    adopted = sug_cnt.get("adopted", 0)
    decided = adopted + sug_cnt.get("ignored", 0)
    adoption = {
        "status_counts": sug_cnt,
        "adopt_rate_pct": _ratio(adopted, decided),
    }

    return {
        "tenant_id": tid,
        "basics": basics,
        "structure": structure,
        "bid_habits": bid_habits,
        "performance": performance,
        "adjust_behavior": adjust_behavior,
        "adoption": adoption,
    }


def profile_brief(p: dict) -> str:
    """把画像压成一段中文，喂进调价建议 prompt（控制长度）。"""
    b, s, bh, perf, adj, ad = (
        p["basics"], p["structure"], p["bid_habits"], p["performance"],
        p["adjust_behavior"], p["adoption"],
    )
    lines = [f"客户：{b['name']}（行业：{b['industry']}）"]
    if b["business_desc"]:
        lines.append(f"业务定位：{b['business_desc']}")
    cat = "、".join(f"{c['label']}{c['count']}" for c in s["category_dist"][:5])
    lines.append(f"账户：{s['keywords']} 词（{cat}），{s['campaigns']} 计划 {s['adgroups']} 单元")
    if bh["avg_diff_vs_guide"] is not None:
        tend = "高于" if bh["avg_diff_vs_guide"] >= 0 else "低于"
        lines.append(
            f"出价习惯：整体相对百度指导价平均{tend} ¥{abs(bh['avg_diff_vs_guide'])}"
            f"（{bh['above_guide_pct']}% 的词高于指导价）"
        )
    if perf.get("kpi"):
        k = perf["kpi"]
        dev = "、".join(f"{d['device']}占{d['cost_share_pct']}%" for d in perf["device_split"])
        lines.append(
            f"近{PERF_DAYS}天：点击率 {round((k['ctr'] or 0) * 100, 2)}%、平均点击成本 ¥{k['cpc']}、"
            f"均排名 {k['avg_rank']}；设备消费 {dev}；平均质量度 {perf['avg_quality']}"
        )
    if adj["total"]:
        lines.append(
            f"调价行为（近{adj['window_days']}天）：{adj['total']} 次，平均幅度 {adj['avg_abs_pct']}%，"
            f"加价 {adj['raise_count']}/降价 {adj['lower_count']}，超 20% 上限 {adj['over_limit']} 次"
        )
    if ad["adopt_rate_pct"] is not None:
        lines.append(f"AI 建议采纳率 {ad['adopt_rate_pct']}%")
    return "\n".join(lines)


SUMMARY_SYSTEM = """你是资深 SEM 优化师。根据给你的某客户的账户画像数据，用 3-4 句中文写一段「客户画像总结」，
点出这个客户的投放特征、出价风格、值得注意的倾向，给后续优化定调。务实、具体，不要套话、不编造数据。
只返回 JSON：{"summary": "..."}"""


async def generate_summary(session: AsyncSession, tenant: Tenant, profile: dict, force: bool = False) -> str | None:
    """AI 画像总结，缓存在 tenants.profile_summary。未配 key 返回 None。"""
    if not is_enabled():
        return None
    if tenant.profile_summary and not force:
        return tenant.profile_summary
    try:
        out = await chat_json(SUMMARY_SYSTEM, profile_brief(profile))
    except DeepSeekError as e:
        logger.warning("客户画像总结生成失败 tenant=%s：%s", tenant.id, e)
        return tenant.profile_summary
    summary = str(out.get("summary") or "")
    if summary:
        tenant.profile_summary = summary
        tenant.profile_generated_at = datetime.utcnow()
        await session.commit()
    return summary


async def build_customer_brief(session: AsyncSession, tenant: Tenant) -> str | None:
    """供调价建议 engine 调用：算一次画像 → brief 文本。失败返回 None（不阻断建议）。"""
    try:
        return profile_brief(await gather_profile(session, tenant))
    except Exception:  # noqa: BLE001
        logger.exception("构建客户画像 brief 失败 tenant=%s", tenant.id)
        return None
