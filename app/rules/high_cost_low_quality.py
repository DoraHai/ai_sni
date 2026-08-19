"""R-02（P1）：高消费低质量度。

交接文档 Day 3 定义为「质量度 ≤ 4 + 消费 > 50 + 零转化」。
转化数据 M2 才接入（爱番番 / ocpc 转化列），当前先落地前两个条件：
当日消费 > 50 元 且 质量度 ≤ 4。转化接入后在 evaluate 里补零转化过滤即可。
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KwReportSnapshot, Tenant
from app.rules.base import AlertDraft

COST_THRESHOLD = Decimal("50")
QUALITY_THRESHOLD = 4


class HighCostLowQualityRule:
    code = "R-02"
    priority = "P1"

    async def evaluate(
        self, session: AsyncSession, tenant: Tenant, target_date: date
    ) -> list[AlertDraft]:
        rows = (
            await session.execute(
                select(
                    KwReportSnapshot.keyword_id,
                    func.max(KwReportSnapshot.keyword),
                    func.max(KwReportSnapshot.campaign_id),
                    func.max(KwReportSnapshot.campaign_name),
                    func.sum(KwReportSnapshot.cost),
                    func.sum(KwReportSnapshot.click),
                    func.min(KwReportSnapshot.quality_enum),
                )
                .where(
                    KwReportSnapshot.tenant_id == tenant.id,
                    KwReportSnapshot.report_date == target_date,
                    KwReportSnapshot.quality_enum.isnot(None),
                    KwReportSnapshot.quality_enum <= QUALITY_THRESHOLD,
                )
                .group_by(KwReportSnapshot.keyword_id)
                .having(func.sum(KwReportSnapshot.cost) > COST_THRESHOLD)
            )
        ).all()

        drafts: list[AlertDraft] = []
        for kw_id, kw, camp_id, camp_name, cost, click, quality in rows:
            cost_f = round(float(cost or 0), 2)
            drafts.append(
                AlertDraft(
                    rule_code=self.code,
                    priority=self.priority,
                    title="高消费关键词质量度偏低",
                    message=(
                        f"关键词「{kw}」{target_date.isoformat()} 消费 ¥{cost_f}，"
                        f"质量度仅 {quality} 分。消费较高但质量度偏低，"
                        f"建议优先排查创意相关性与落地页体验，避免预算低效消耗。"
                    ),
                    report_date=target_date,
                    keyword_id=kw_id,
                    keyword=kw,
                    campaign_id=camp_id,
                    campaign_name=camp_name,
                    metrics={
                        "消费": cost_f,
                        "点击": int(click or 0),
                        "质量度": int(quality),
                    },
                )
            )
        return drafts
