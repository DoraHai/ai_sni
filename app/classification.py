"""关键词 5 类分级（业务规则之首）。

自动分类优先级（category_source='manual' 的行永不覆盖）：
  1. brand    品牌词：字面含任一品牌词根（tenants.brand_terms，缺省回退 tenants.name）
  2. focus    重点词：近7天消费排名前20 且 近7天消费 > 100
  3. new      新词：累计展现 < 20
  4. longtail 长尾精准：关键词字数 > 7
  5. normal   一般词：兜底

近7天窗口口径与工作台 metrics_7d 一致：锚定租户 KwReportSnapshot 最新有数日期，
往前推 6 天，避免自然日历口径下当日/昨日数据未同步完整导致分类抖动。
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Keyword, KwReportSnapshot, Tenant

logger = logging.getLogger(__name__)

NEW_WORD_IMPRESSION_THRESHOLD = 20
LONGTAIL_MIN_LENGTH = 7
FOCUS_TOP_N = 20
FOCUS_MIN_COST = 100.0


def classify_one(
    keyword_text: str,
    total_impression: int,
    brand_terms: list[str],
    cost_7d: float | None,
    is_top_focus: bool,
) -> str:
    text = (keyword_text or "").lower()
    if any(term.lower() in text for term in brand_terms):
        return "brand"
    if is_top_focus and cost_7d is not None and cost_7d > FOCUS_MIN_COST:
        return "focus"
    if total_impression < NEW_WORD_IMPRESSION_THRESHOLD:
        return "new"
    if len(keyword_text or "") > LONGTAIL_MIN_LENGTH:
        return "longtail"
    return "normal"


async def _compute_context(session: AsyncSession, tenant: Tenant) -> dict:
    """计算分类需要的共享上下文：累计展现、近7天消费、消费TOP20排名。"""
    tid = tenant.id

    imp_rows = (
        await session.execute(
            select(
                KwReportSnapshot.keyword_id,
                func.coalesce(func.sum(KwReportSnapshot.impression), 0),
            )
            .where(KwReportSnapshot.tenant_id == tid)
            .group_by(KwReportSnapshot.keyword_id)
        )
    ).all()
    impressions = {kw_id: int(n) for kw_id, n in imp_rows}

    max_date = await session.scalar(
        select(func.max(KwReportSnapshot.report_date)).where(
            KwReportSnapshot.tenant_id == tid
        )
    )
    cost_7d_map: dict[int, float] = {}
    top20_ids: set[int] = set()
    if max_date is not None:
        start = max_date - timedelta(days=6)
        cost_rows = (
            await session.execute(
                select(
                    KwReportSnapshot.keyword_id,
                    func.coalesce(func.sum(KwReportSnapshot.cost), 0),
                )
                .where(
                    KwReportSnapshot.tenant_id == tid,
                    KwReportSnapshot.report_date >= start,
                    KwReportSnapshot.report_date <= max_date,
                )
                .group_by(KwReportSnapshot.keyword_id)
            )
        ).all()
        cost_7d_map = {kw_id: float(c or 0) for kw_id, c in cost_rows}
        ranked = sorted(cost_7d_map.items(), key=lambda x: -x[1])[:FOCUS_TOP_N]
        top20_ids = {kw_id for kw_id, _ in ranked}

    return {
        "impressions": impressions,
        "cost_7d_map": cost_7d_map,
        "top20_ids": top20_ids,
        "max_date": max_date,
    }


def _brand_terms(tenant: Tenant) -> list[str]:
    terms = [t.strip() for t in (tenant.brand_terms or []) if t and t.strip()]
    if not terms and tenant.name:
        terms = [tenant.name.strip()]
    return terms


async def preview_reclassify(session: AsyncSession, tenant: Tenant) -> dict:
    """预演：按新规则重算，但不落库，只返回会变化的词清单，供人工确认。"""
    brand_terms = _brand_terms(tenant)
    ctx = await _compute_context(session, tenant)
    rows = (
        await session.scalars(
            select(Keyword).where(
                Keyword.tenant_id == tenant.id,
                Keyword.category_source != "manual",
            )
        )
    ).all()

    changes = []
    new_counts: dict[str, int] = {}
    old_counts: dict[str, int] = {}
    for kw in rows:
        old_cat = kw.category or "normal"
        old_counts[old_cat] = old_counts.get(old_cat, 0) + 1

        impression = ctx["impressions"].get(kw.keyword_id, kw.total_impression or 0)
        cost_7d = ctx["cost_7d_map"].get(kw.keyword_id)
        is_top = kw.keyword_id in ctx["top20_ids"]
        new_cat = classify_one(kw.keyword, impression, brand_terms, cost_7d, is_top)
        new_counts[new_cat] = new_counts.get(new_cat, 0) + 1

        if new_cat != old_cat:
            changes.append(
                {
                    "keyword_id": kw.keyword_id,
                    "keyword": kw.keyword,
                    "old_category": old_cat,
                    "new_category": new_cat,
                    "total_impression": impression,
                    "cost_7d": round(cost_7d, 2) if cost_7d is not None else None,
                }
            )

    return {
        "max_date": ctx["max_date"].isoformat() if ctx["max_date"] else None,
        "total_auto_keywords": len(rows),
        "changed_count": len(changes),
        "old_category_counts": old_counts,
        "new_category_counts": new_counts,
        "changes": changes[:500],
    }


async def reclassify_keywords(session: AsyncSession, tenant: Tenant) -> dict[str, int]:
    """重算某租户所有 auto 分级关键词并落库。返回各分类条数（含 manual 的现状）。"""
    brand_terms = _brand_terms(tenant)
    ctx = await _compute_context(session, tenant)
    rows = (
        await session.scalars(select(Keyword).where(Keyword.tenant_id == tenant.id))
    ).all()

    counts: dict[str, int] = {}
    now = datetime.utcnow()
    for kw in rows:
        kw.total_impression = ctx["impressions"].get(kw.keyword_id, 0)
        if kw.category_source != "manual":
            cost_7d = ctx["cost_7d_map"].get(kw.keyword_id)
            is_top = kw.keyword_id in ctx["top20_ids"]
            new_cat = classify_one(
                kw.keyword, kw.total_impression, brand_terms, cost_7d, is_top
            )
            if kw.category != new_cat:
                kw.category = new_cat
                kw.category_updated_at = now
        counts[kw.category] = counts.get(kw.category, 0) + 1

    await session.commit()
    logger.info("租户 %s 关键词分级重算完成: %s", tenant.id, counts)
    return counts
