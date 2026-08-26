"""R-14（P0）：品牌词排名失守。

业务规则：品牌词必须第一位，跌出立即提价（原型「关键词 5 类分级」P0 行）。
判定：品牌词当日平均排名 > 1.5，且当日展现 ≥ 5（展现 1-2 次的"平均排名"
只是单次碰巧的位置，没有统计意义，不值得 P0）。

品牌词识别：优先用 keywords 表的 5 类分级（category='brand'，含人工标的）；
该租户尚无分级数据时回退过渡方案"关键词包含租户品牌词根"（词根取 tenants.name）。
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Keyword, KwReportSnapshot, Tenant
from app.classification import resolve_brand_terms
from app.rules.base import AlertDraft

RANK_THRESHOLD = Decimal("1.5")
MIN_IMPRESSION = 5  # 当日展现低于此值不评估排名


class BrandRankRule:
    code = "R-14"
    priority = "P0"

    async def evaluate(
        self, session: AsyncSession, tenant: Tenant, target_date: date
    ) -> list[AlertDraft]:
        # 人工/自动分级和字面品牌词根取并集，避免告警与工作台品牌筛选口径打架。
        brand_ids = (
            await session.scalars(
                select(Keyword.keyword_id).where(
                    Keyword.tenant_id == tenant.id, Keyword.category == "brand"
                )
            )
        ).all()
        brand_terms = resolve_brand_terms(tenant)
        brand_parts = [KwReportSnapshot.keyword_id.in_(brand_ids)] if brand_ids else []
        brand_parts.extend(
            KwReportSnapshot.keyword.ilike(f"%{term}%") for term in brand_terms
        )
        if not brand_parts:
            return []
        brand_cond = or_(*brand_parts)

        # 同一关键词多设备行：按消费加权平均排名，取消费/点击合计
        rows = (
            await session.execute(
                select(
                    KwReportSnapshot.keyword_id,
                    func.max(KwReportSnapshot.keyword),
                    func.max(KwReportSnapshot.campaign_id),
                    func.max(KwReportSnapshot.campaign_name),
                    func.avg(KwReportSnapshot.avg_rank),
                    func.sum(KwReportSnapshot.cost),
                    func.sum(KwReportSnapshot.impression),
                )
                .where(
                    KwReportSnapshot.tenant_id == tenant.id,
                    KwReportSnapshot.report_date == target_date,
                    brand_cond,
                    KwReportSnapshot.avg_rank.isnot(None),
                )
                .group_by(KwReportSnapshot.keyword_id)
                .having(
                    func.avg(KwReportSnapshot.avg_rank) > RANK_THRESHOLD,
                    func.sum(KwReportSnapshot.impression) >= MIN_IMPRESSION,
                )
            )
        ).all()

        drafts: list[AlertDraft] = []
        for kw_id, kw, camp_id, camp_name, rank, cost, imp in rows:
            rank_f = round(float(rank), 2)
            drafts.append(
                AlertDraft(
                    rule_code=self.code,
                    priority=self.priority,
                    title="品牌词排名失守",
                    message=(
                        f"品牌词「{kw}」{target_date.isoformat()} 平均排名 {rank_f}，"
                        f"已跌出第一位。品牌词要求稳定在首位，建议立即检查出价并提价，"
                        f"防止竞品截流。"
                    ),
                    report_date=target_date,
                    keyword_id=kw_id,
                    keyword=kw,
                    campaign_id=camp_id,
                    campaign_name=camp_name,
                    metrics={
                        "平均排名": rank_f,
                        "消费": float(cost or 0),
                        "展现": int(imp or 0),
                    },
                )
            )
        return drafts
