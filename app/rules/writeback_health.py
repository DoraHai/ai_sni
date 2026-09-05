"""Surface unresolved real writes through the existing SEM alert inbox."""
from datetime import timedelta

from sqlalchemy import DateTime, cast, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import Alert, BidWriteback, WritebackAction
from app.models.writeback_action import WRITEBACK_ACTION_LABELS

PENDING_TIMEOUT = timedelta(minutes=15)
SOURCES = (("bid", BidWriteback), ("action", WritebackAction))


def unresolved(model):
    return (
        model.dry_run.is_(False),
        model.status.in_(("pending", "reconcile")),
    )


def alert_record(tenant_id, kind, row, age_seconds):
    minutes = max(0, int(age_seconds or 0) // 60)
    action = "关键词出价" if kind == "bid" else WRITEBACK_ACTION_LABELS.get(row.action_type, "账户操作")
    return dict(
        tenant_id=tenant_id,
        rule_code=f"WB-{kind}",
        entity_ref=f"writeback:{kind}:{row.id}",
        # Anchor identity to the original record, not the polling day.
        report_date=row.created_at.date(),
        keyword_id=None,
        campaign_id=row.campaign_id,
        campaign_name=row.campaign_name,
        priority="P1",
        status="open",
        title="真实回写待人工对账",
        message=(f"客户 #{tenant_id}，推广账户 #{row.baidu_account_id or '未知'}，"
                 f"{action}记录 #{row.id} 已等待 {minutes} 分钟。"
                 "执行结果尚未确认，请到效果验证的人工对账队列核对百度结果，勿重复提交。"),
        metrics=dict(record_type=kind, record_id=row.id,
                     baidu_account_id=row.baidu_account_id, action_type=action,
                     writeback_status=row.status, age_minutes=minutes,
                     href="/verify/pending?mode=queue"),
    )


async def refresh_writeback_alerts(session, tenant_id):
    """Caller owns the per-tenant transaction; never calls the advertising API."""
    count = 0
    for kind, model in SOURCES:
        # created_at uses database now() into a naive timestamp column. Compare
        # in the same DB/session timezone, not against application UTC values.
        db_now = cast(func.now(), DateTime)
        age = func.extract("epoch", db_now - model.created_at)
        stmt = select(model, age).where(
            model.tenant_id == tenant_id, *unresolved(model),
            or_(model.status == "reconcile",
                model.created_at <= db_now - PENDING_TIMEOUT),
        ).order_by(model.id)
        # Stream in bounded batches; do not build a giant INSERT statement.
        stream = await session.stream(stmt.execution_options(yield_per=200))
        async for row, seconds in stream:
            record = alert_record(tenant_id, kind, row, seconds)
            insert = pg_insert(Alert).values(**record)
            await session.execute(insert.on_conflict_do_update(
                index_elements=["tenant_id", "rule_code", "entity_ref", "report_date"],
                index_where=Alert.entity_ref.isnot(None),
                set_={key: record[key] for key in ("message", "metrics", "status", "priority")}
                     | {"resolved_at": None},
            ))
            count += 1

        # Recheck the source in SQL so completion during polling is respected.
        still_unresolved = exists(select(model.id).where(
            model.tenant_id == Alert.tenant_id,
            func.concat(f"writeback:{kind}:", model.id) == Alert.entity_ref,
            *unresolved(model),
        ))
        await session.execute(update(Alert).where(
            Alert.tenant_id == tenant_id,
            Alert.rule_code == f"WB-{kind}",
            Alert.status.in_(("open", "merged")),
            ~still_unresolved,
        ).values(status="resolved", resolved_at=func.now()))
    return count
