"""Rule engine: evaluate alert rules, upsert alerts, and merge stale duplicates."""
import logging
from datetime import date

from sqlalchemy import exists, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Alert, Tenant
from app.module_scope import list_active_module_tenants
from app.rules.ai_anomaly import AIAnomalyRule
from app.rules.base import Rule
from app.rules.brand_rank import BrandRankRule
from app.rules.budget_overrun import BudgetOverrunRule
from app.rules.high_cost_low_quality import HighCostLowQualityRule
from app.rules.keyword_shortage import KeywordShortageRule

logger = logging.getLogger(__name__)

ALL_RULES: list[Rule] = [
    BrandRankRule(),
    HighCostLowQualityRule(),
    BudgetOverrunRule(),
    KeywordShortageRule(),
    AIAnomalyRule(),
]


async def merge_duplicate_alerts(session: AsyncSession, tenant_id: int) -> int:
    """Merge older open alerts for the same keyword/entity when a newer alert exists."""
    newer = aliased(Alert)
    result_kw = await session.execute(
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
    result_entity = await session.execute(
        update(Alert)
        .where(
            Alert.tenant_id == tenant_id,
            Alert.status == "open",
            Alert.entity_ref.isnot(None),
            exists().where(
                newer.tenant_id == Alert.tenant_id,
                newer.rule_code == Alert.rule_code,
                newer.entity_ref == Alert.entity_ref,
                newer.report_date > Alert.report_date,
            ),
        )
        .values(status="merged")
    )
    await session.commit()
    return (result_kw.rowcount or 0) + (result_entity.rowcount or 0)


def _alert_record(tenant: Tenant, draft) -> dict:
    return {
        "tenant_id": tenant.id,
        "rule_code": draft.rule_code,
        "priority": draft.priority,
        "title": draft.title,
        "message": draft.message,
        "report_date": draft.report_date,
        "keyword_id": draft.keyword_id,
        "keyword": draft.keyword,
        "campaign_id": draft.campaign_id,
        "campaign_name": draft.campaign_name,
        "entity_ref": draft.entity_ref,
        "metrics": draft.metrics,
        "status": "open",
    }


def _dedupe_alert_records(records: list[dict]) -> list[dict]:
    """Collapse duplicate records before a bulk upsert reaches PostgreSQL."""
    deduped: dict[tuple, dict] = {}
    ordered_keys: list[tuple] = []
    for record in records:
        if record["keyword_id"] is not None:
            key = (
                "keyword",
                record["tenant_id"],
                record["rule_code"],
                record["keyword_id"],
                record["report_date"],
            )
        elif record["entity_ref"] is not None:
            key = (
                "entity",
                record["tenant_id"],
                record["rule_code"],
                record["entity_ref"],
                record["report_date"],
            )
        else:
            key = ("skip", id(record))
        if key not in deduped:
            ordered_keys.append(key)
        deduped[key] = record
    return [deduped[key] for key in ordered_keys]


async def _upsert_keyword_alerts(session: AsyncSession, records: list[dict]) -> None:
    if not records:
        return
    stmt = pg_insert(Alert).values(records)
    stmt = stmt.on_conflict_do_update(
        index_elements=["tenant_id", "rule_code", "keyword_id", "report_date"],
        index_where=Alert.keyword_id.isnot(None),
        set_={
            "priority": stmt.excluded.priority,
            "status": stmt.excluded.status,
            "title": stmt.excluded.title,
            "message": stmt.excluded.message,
            "campaign_id": stmt.excluded.campaign_id,
            "campaign_name": stmt.excluded.campaign_name,
            "metrics": stmt.excluded.metrics,
        },
    )
    await session.execute(stmt)


async def _upsert_entity_alerts(session: AsyncSession, records: list[dict]) -> None:
    if not records:
        return
    stmt = pg_insert(Alert).values(records)
    stmt = stmt.on_conflict_do_update(
        index_elements=["tenant_id", "rule_code", "entity_ref", "report_date"],
        index_where=Alert.entity_ref.isnot(None),
        set_={
            "priority": stmt.excluded.priority,
            "status": stmt.excluded.status,
            "title": stmt.excluded.title,
            "message": stmt.excluded.message,
            "campaign_id": stmt.excluded.campaign_id,
            "campaign_name": stmt.excluded.campaign_name,
            "metrics": stmt.excluded.metrics,
        },
    )
    await session.execute(stmt)


async def run_rules_for_tenant(
    session: AsyncSession, tenant: Tenant, target_date: date
) -> int:
    """Evaluate all daily rules for one tenant and return written/refreshed alert count."""
    drafts = []
    for rule in ALL_RULES:
        try:
            drafts.extend(await rule.evaluate(session, tenant, target_date))
        except Exception:  # noqa: BLE001
            logger.exception(
                "rule %s failed for tenant %s date %s", rule.code, tenant.id, target_date
            )

    if not drafts:
        merged = await merge_duplicate_alerts(session, tenant.id)
        if merged:
            logger.info("tenant %s merged %d stale alerts", tenant.id, merged)
        return 0

    records = _dedupe_alert_records([_alert_record(tenant, draft) for draft in drafts])
    kw_records = [r for r in records if r["keyword_id"] is not None]
    entity_records = [
        r for r in records if r["keyword_id"] is None and r["entity_ref"] is not None
    ]
    skipped = len(records) - len(kw_records) - len(entity_records)
    if skipped:
        logger.warning(
            "tenant %s skipped %d alerts without keyword_id/entity_ref", tenant.id, skipped
        )

    await _upsert_keyword_alerts(session, kw_records)
    await _upsert_entity_alerts(session, entity_records)
    await session.commit()

    merged = await merge_duplicate_alerts(session, tenant.id)
    logger.info(
        "tenant %s %s rule engine wrote %d alerts, merged %d alerts",
        tenant.id,
        target_date,
        len(kw_records) + len(entity_records),
        merged,
    )
    return len(kw_records) + len(entity_records)


async def run_rules_for_all_tenants(
    session: AsyncSession, target_date: date
) -> dict[str, int]:
    """Evaluate daily rules for all tenants."""
    tenants = await list_active_module_tenants(session, "sem")
    result: dict[str, int] = {}
    for tenant in tenants:
        try:
            result[tenant.name] = await run_rules_for_tenant(session, tenant, target_date)
        except Exception:  # noqa: BLE001
            logger.exception("tenant %s rule engine failed", tenant.name)
            result[tenant.name] = -1
    return result
