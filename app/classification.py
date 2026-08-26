"""关键词 5 类分级（业务规则之首）。

自动分类优先级（category_source='manual' 的行永不覆盖）：
  1. brand 品牌词：字面含任一品牌词根（tenants.brand_terms，缺省回退 tenants.name）
  2. focus 重点词：百度物料标签 tabs 含 31（重点关键词，文档 0066）
  3. new   新词：累计展现 < 20（业务规则：新词 <20 展现不评估）
  4. normal 一般词：兜底
  longtail 长尾精准词只能人工标（业务定义靠运营辨识，自动规则不产出）。
"""
import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Keyword, KwReportSnapshot, Tenant

logger = logging.getLogger(__name__)

NEW_WORD_IMPRESSION_THRESHOLD = 20


def resolve_brand_terms(tenant: Tenant) -> list[str]:
    """返回租户统一的品牌词根，供分级、筛选和告警共用。"""
    terms = [t.strip() for t in (tenant.brand_terms or []) if t and t.strip()]
    if not terms and tenant.name and tenant.name.strip():
        terms = [tenant.name.strip()]
    # 保序去重，避免配置里大小写或空格不同的重复词根。
    return list(dict.fromkeys(term.casefold() for term in terms))


def classify_one(keyword_text: str, tabs: list | None, total_impression: int, brand_terms: list[str]) -> str:
    text = (keyword_text or "").lower()
    if any(term.lower() in text for term in brand_terms):
        return "brand"
    if tabs and 31 in tabs:
        return "focus"
    if total_impression < NEW_WORD_IMPRESSION_THRESHOLD:
        return "new"
    return "normal"


async def reclassify_keywords(session: AsyncSession, tenant: Tenant) -> dict[str, int]:
    """重算某租户所有 auto 分级关键词。返回各分类条数（含 manual 的现状）。"""
    brand_terms = resolve_brand_terms(tenant)

    # 累计展现（全期）
    imp_rows = (
        await session.execute(
            select(
                KwReportSnapshot.keyword_id,
                func.coalesce(func.sum(KwReportSnapshot.impression), 0),
            )
            .where(KwReportSnapshot.tenant_id == tenant.id)
            .group_by(KwReportSnapshot.keyword_id)
        )
    ).all()
    impressions = {kw_id: int(n) for kw_id, n in imp_rows}

    rows = (
        await session.scalars(select(Keyword).where(Keyword.tenant_id == tenant.id))
    ).all()

    counts: dict[str, int] = {}
    now = datetime.utcnow()
    for kw in rows:
        kw.total_impression = impressions.get(kw.keyword_id, 0)
        if kw.category_source != "manual":
            new_cat = classify_one(
                kw.keyword, kw.tabs, kw.total_impression, brand_terms
            )
            if kw.category != new_cat:
                kw.category = new_cat
                kw.category_updated_at = now
        counts[kw.category] = counts.get(kw.category, 0) + 1

    await session.commit()
    logger.info("租户 %s 关键词分级重算完成: %s", tenant.id, counts)
    return counts
