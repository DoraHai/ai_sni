"""Real SQL coverage in a disposable localhost database; no migrations."""
import asyncio
import os

import pytest
from sqlalchemy import ForeignKeyConstraint, MetaData, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

# Reuse the non-production import configuration from the unit test module.
from test_sem_writeback_health import alert_record  # noqa: F401
from app.models import Alert, BidWriteback, WritebackAction
from app.rules.writeback_health import refresh_writeback_alerts


@pytest.mark.parametrize("zone", ["UTC", "Asia/Shanghai"])
def test_postgres_writeback_alert_lifecycle(zone):
    url = os.environ.get("SEM_ALERT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires disposable SEM_ALERT_TEST_DATABASE_URL")
    parsed = make_url(url)
    assert parsed.host in {"localhost", "127.0.0.1"}
    assert parsed.database == "sem_writeback_test"

    async def run():
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT set_config('TimeZone', :zone, false)"), {"zone": zone})
                # Only session-local tables: no real tables or customer data touched.
                for model in (Alert, BidWriteback, WritebackAction):
                    table = model.__table__.to_metadata(MetaData())
                    table._prefixes = ["TEMPORARY"]
                    for constraint in list(table.constraints):
                        if isinstance(constraint, ForeignKeyConstraint):
                            table.constraints.remove(constraint)
                    await conn.run_sync(lambda sync, t=table: t.create(sync))
                async with AsyncSession(bind=conn, expire_on_commit=False) as session:
                    now = await session.scalar(text("SELECT LOCALTIMESTAMP"))
                    from datetime import timedelta
                    def bid(id, status, minutes, tenant=3, dry=False):
                        return BidWriteback(id=id, tenant_id=tenant, keyword_id=id,
                            new_bid=1, dry_run=dry, status=status,
                            created_at=now-timedelta(minutes=minutes))
                    session.add_all([
                        bid(1, "pending", 16), bid(2, "pending", 14),
                        bid(3, "reconcile", 0), bid(4, "pending", 60, dry=True),
                        bid(5, "pending", 60, tenant=4), bid(6, "success", 60),
                        bid(7, "failed", 60), bid(8, "pending", 2880),
                        WritebackAction(id=1, tenant_id=3, action_type="set_account_budget",
                            word="test", dry_run=False, status="reconcile", created_at=now),
                    ])
                    await session.flush()
                    assert await refresh_writeback_alerts(session, 3) == 4
                    await session.flush()
                    alerts = list((await session.scalars(select(Alert))).all())
                    assert len(alerts) == 4
                    identities = {a.entity_ref: (a.id, a.report_date) for a in alerts}
                    assert set(identities) == {"writeback:bid:1", "writeback:bid:3", "writeback:bid:8", "writeback:action:1"}
                    assert identities["writeback:bid:8"][1] == (now-timedelta(days=2)).date()
                    await session.execute(update(Alert).values(status="resolved", resolved_at=now))
                    await refresh_writeback_alerts(session, 3)
                    session.expire_all()
                    alerts = list((await session.scalars(select(Alert))).all())
                    assert {a.entity_ref: (a.id, a.report_date) for a in alerts} == identities
                    assert all(a.status == "open" and a.resolved_at is None for a in alerts)
                    await session.execute(update(BidWriteback).where(BidWriteback.id == 1).values(status="success"))
                    await session.execute(update(WritebackAction).values(status="failed"))
                    await refresh_writeback_alerts(session, 3)
                    session.expire_all()
                    alerts = list((await session.scalars(select(Alert))).all())
                    assert {a.entity_ref for a in alerts if a.status == "resolved"} == {"writeback:bid:1", "writeback:action:1"}
                    assert await session.scalar(select(func.count()).select_from(Alert)) == 4
        finally:
            await engine.dispose()
    asyncio.run(run())
