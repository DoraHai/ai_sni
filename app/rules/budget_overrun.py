"""预算撞线规则：账户级 + 计划级。"""
import logging
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.baidu.services.account import AccountService
from app.baidu.sync import _account_client, _to_float, _to_int
from app.models import BaiduAccount, Campaign, KwReportSnapshot, Tenant
from app.rules.base import AlertDraft

logger = logging.getLogger(__name__)

BUDGET_OVERRUN_THRESHOLD_PCT = 95


class BudgetOverrunRule:
    code = "R-BUDGET"
    priority = "P1"

    async def evaluate(
        self, session: AsyncSession, tenant: Tenant, target_date: date
    ) -> list[AlertDraft]:
        drafts: list[AlertDraft] = []
        drafts.extend(await self._account_alerts(session, tenant, target_date))
        drafts.extend(await self._campaign_alerts(session, tenant, target_date))
        return drafts

    async def _account_alerts(
        self, session: AsyncSession, tenant: Tenant, target_date: date
    ) -> list[AlertDraft]:
        tenant_daily_cost = (
            await session.scalar(
                select(func.coalesce(func.sum(KwReportSnapshot.cost), 0)).where(
                    KwReportSnapshot.tenant_id == tenant.id,
                    KwReportSnapshot.report_date == target_date,
                )
            )
        )
        cost = float(tenant_daily_cost or 0)
        accounts = (
            await session.scalars(
                select(BaiduAccount).where(
                    BaiduAccount.tenant_id == tenant.id,
                    BaiduAccount.status == "active",
                )
            )
        ).all()
        drafts: list[AlertDraft] = []
        for acc in accounts:
            try:
                resp = await AccountService(_account_client(acc)).get_account_info(
                    ["budget", "budgetType"]
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("账户预算撞线检查失败 tenant=%s account=%s: %s", tenant.id, acc.id, exc)
                continue

            info = resp.get("data") if isinstance(resp, dict) else resp
            if isinstance(info, list):
                info = info[0] if info else {}
            if not isinstance(info, dict):
                info = {}

            budget = _to_float(info.get("budget"))
            budget_type = _to_int(info.get("budgetType"))
            if budget_type != 1 or not budget or budget <= 0:
                continue
            usage_pct = round(cost / budget * 100, 1)
            if usage_pct >= BUDGET_OVERRUN_THRESHOLD_PCT:
                drafts.append(
                    AlertDraft(
                        rule_code=self.code,
                        priority=self.priority,
                        title=f"账户预算即将撞线（{usage_pct}%）",
                        message=(
                            f"账户「{acc.baidu_username}」{target_date.isoformat()} 消费 ¥{cost:.2f}，"
                            f"已达当前日预算 ¥{budget:.2f} 的 {usage_pct}%"
                            "（注：预算为当前实时值，非该日历史快照）。"
                        ),
                        report_date=target_date,
                        entity_ref=f"account:{acc.id}",
                        metrics={
                            "budget": budget,
                            "cost": cost,
                            "usage_pct": usage_pct,
                            "cost_source": "kw_report_snapshots",
                            "budget_as_of": "当前实时值，非历史快照",
                        },
                    )
                )
        return drafts

    async def _campaign_alerts(
        self, session: AsyncSession, tenant: Tenant, target_date: date
    ) -> list[AlertDraft]:
        campaigns = (
            await session.scalars(
                select(Campaign).where(
                    Campaign.tenant_id == tenant.id,
                    Campaign.pause.isnot(True),
                    Campaign.budget.isnot(None),
                )
            )
        ).all()
        if not campaigns:
            return []

        camp_ids = [c.campaign_id for c in campaigns if c.campaign_id is not None]
        cost_rows = (
            await session.execute(
                select(KwReportSnapshot.campaign_id, func.sum(KwReportSnapshot.cost))
                .where(
                    KwReportSnapshot.tenant_id == tenant.id,
                    KwReportSnapshot.report_date == target_date,
                    KwReportSnapshot.campaign_id.in_(camp_ids),
                )
                .group_by(KwReportSnapshot.campaign_id)
            )
        ).all()
        cost_map = {cid: float(cost or 0) for cid, cost in cost_rows}

        drafts: list[AlertDraft] = []
        for camp in campaigns:
            if camp.campaign_id is None or camp.budget is None:
                continue
            budget = float(camp.budget)
            if budget <= 0:
                continue
            cost = cost_map.get(camp.campaign_id, 0.0)
            usage_pct = round(cost / budget * 100, 1)
            if usage_pct >= BUDGET_OVERRUN_THRESHOLD_PCT:
                drafts.append(
                    AlertDraft(
                        rule_code=self.code,
                        priority=self.priority,
                        title=f"计划预算即将撞线（{usage_pct}%）",
                        message=(
                            f"计划「{camp.campaign_name or camp.campaign_id}」当日消费 ¥{cost:.2f}，"
                            f"已达日预算 ¥{budget:.2f} 的 {usage_pct}%。"
                        ),
                        report_date=target_date,
                        campaign_id=camp.campaign_id,
                        campaign_name=camp.campaign_name,
                        entity_ref=f"campaign:{camp.campaign_id}",
                        metrics={"budget": budget, "cost": cost, "usage_pct": usage_pct},
                    )
                )
        return drafts
