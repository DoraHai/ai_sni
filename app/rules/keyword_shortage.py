"""Keyword shortage rule: enabled adgroups should have enough active keywords."""
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Adgroup, Keyword, Tenant
from app.rules.base import AlertDraft

MIN_ACTIVE_KEYWORDS = 5


class KeywordShortageRule:
    code = "R-KWSHORT"
    priority = "P2"

    async def evaluate(
        self, session: AsyncSession, tenant: Tenant, target_date: date
    ) -> list[AlertDraft]:
        adgroups = (
            await session.scalars(
                select(Adgroup).where(
                    Adgroup.tenant_id == tenant.id,
                    Adgroup.pause.isnot(True),
                    Adgroup.adgroup_id.isnot(None),
                )
            )
        ).all()
        if not adgroups:
            return []

        adgroup_ids = [adgroup.adgroup_id for adgroup in adgroups]
        count_rows = (
            await session.execute(
                select(Keyword.adgroup_id, func.count())
                .where(
                    Keyword.tenant_id == tenant.id,
                    Keyword.adgroup_id.in_(adgroup_ids),
                    Keyword.pause.isnot(True),
                )
                .group_by(Keyword.adgroup_id)
            )
        ).all()
        count_map = {adgroup_id: int(count) for adgroup_id, count in count_rows}

        drafts: list[AlertDraft] = []
        for adgroup in adgroups:
            keyword_count = count_map.get(adgroup.adgroup_id, 0)
            if keyword_count >= MIN_ACTIVE_KEYWORDS:
                continue
            drafts.append(
                AlertDraft(
                    rule_code=self.code,
                    priority=self.priority,
                    title=f"单元关键词数量过少（{keyword_count}个）",
                    message=(
                        f"单元「{adgroup.adgroup_name or adgroup.adgroup_id}」目前只有 "
                        f"{keyword_count} 个有效关键词，建议补充拓词。"
                    ),
                    report_date=target_date,
                    campaign_id=adgroup.campaign_id,
                    campaign_name=None,
                    entity_ref=f"adgroup:{adgroup.adgroup_id}",
                    metrics={
                        "keyword_count": keyword_count,
                        "threshold": MIN_ACTIVE_KEYWORDS,
                    },
                )
            )
        return drafts
