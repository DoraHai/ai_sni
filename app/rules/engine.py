"""规则引擎：跑所有规则 → upsert alerts → 同词归并。

幂等：同 (tenant_id, rule_code, keyword_id, report_date) 重复跑只刷新
title/message/metrics/priority/status，不重复建告警；重新命中恢复 open。

同词归并：同一规则同一关键词多天触发时，只保留数据日期最新的一条 open，
更早的 open 自动改为 merged（避免长期问题在列表里刷出一串）。
merged 是系统行为，与人工 resolved 区分；最新一条若已被人工处理（resolved），
更早的 open 同样归并掉——该问题的最新状态已被处理过。
"""
import logging
from datetime import date

from sqlalchemy import exists, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Alert, Tenant
from app.rules.ai_anomaly import AIAnomalyRule
from app.rules.base import Rule
from app.rules.brand_rank import BrandRankRule
from app.rules.high_cost_low_quality import HighCostLowQualityRule

logger = logging.getLogger(__name__)

ALL_RULES: list[Rule] = [
    BrandRankRule(),
    HighCostLowQualityRule(),
    AIAnomalyRule(),  # AI 异常扫描（环比预筛 + AI 判断；未配 DeepSeek 时降级为空）
]


async def merge_duplicate_alerts(session: AsyncSession, tenant_id: int) -> int:
    """同词归并：把存在更新数据日期同组告警的 open 告警改为 merged。

    分组键 (rule_code, keyword_id)。每次引擎跑完调用，乱序回灌历史日期也能收敛。
    返回归并条数。
    """
    newer = aliased(Alert)
    result = await session.execute(
        update(Alert)
        .where(
            Alert.tenant_id == tenant_id,
            Alert.status == "open",
            Alert.keyword_id.isnot(None),
            exists().where(
                newer.tenant_id == Alert.tenant_id,
                newer.rule_code == Alert.rule_code,
                newer.keyword_id == Alert.keyword_id,
                newer.report_date > Alert.report_date,
            ),
        )
        .values(status="merged")
    )
    await session.commit()
    return result.rowcount or 0


async def run_rules_for_tenant(
    session: AsyncSession, tenant: Tenant, target_date: date
) -> int:
    """对单租户单日跑全部规则，返回写入/刷新的告警条数。"""
    drafts = []
    for rule in ALL_RULES:
        try:
            drafts.extend(await rule.evaluate(session, tenant, target_date))
        except Exception:  # noqa: BLE001
            logger.exception(
                "规则 %s 在租户 %s %s 执行失败", rule.code, tenant.id, target_date
            )

    if not drafts:
        # 没有新告警也跑一次归并：回灌历史日期时让已有告警收敛
        merged = await merge_duplicate_alerts(session, tenant.id)
        if merged:
            logger.info("租户 %s 同词归并 %d 条历史告警", tenant.id, merged)
        return 0

    records = [
        {
            "tenant_id": tenant.id,
            "rule_code": d.rule_code,
            "priority": d.priority,
            "status": "open",
            "title": d.title,
            "message": d.message,
            "report_date": d.report_date,
            "keyword_id": d.keyword_id,
            "keyword": d.keyword,
            "campaign_id": d.campaign_id,
            "campaign_name": d.campaign_name,
            "metrics": d.metrics,
        }
        for d in drafts
    ]
    stmt = pg_insert(Alert).values(records)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_alerts_tenant_rule_kw_date",
        set_={
            "title": stmt.excluded.title,
            "message": stmt.excluded.message,
            "metrics": stmt.excluded.metrics,
            "priority": stmt.excluded.priority,
            "status": stmt.excluded.status,
            "campaign_id": stmt.excluded.campaign_id,
            "campaign_name": stmt.excluded.campaign_name,
        },
    )
    await session.execute(stmt)
    await session.commit()

    merged = await merge_duplicate_alerts(session, tenant.id)
    logger.info(
        "租户 %s %s 规则引擎产出 %d 条告警，同词归并 %d 条",
        tenant.id,
        target_date,
        len(records),
        merged,
    )
    return len(records)


async def run_rules_for_all_tenants(
    session: AsyncSession, target_date: date
) -> dict[str, int]:
    """对所有租户跑规则（每日同步报告后调用）。返回 {租户名: 条数}。"""
    tenants = (await session.scalars(select(Tenant))).all()
    result: dict[str, int] = {}
    for t in tenants:
        try:
            result[t.name] = await run_rules_for_tenant(session, t, target_date)
        except Exception:  # noqa: BLE001
            logger.exception("租户 %s 规则引擎执行失败", t.name)
            result[t.name] = -1
    return result
