"""Native PostgreSQL checks for non-funds writeback intent races."""
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import ForeignKeyConstraint, MetaData, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from app.baidu.writeback import (
    CAMPAIGN_PAUSE_CONFLICT_ACTIONS,
    WritebackError,
    _ensure_no_unresolved_funds_writeback,
    _relock_action_intent,
)
from app.models import BaiduAccount, Campaign, WritebackAction


@asynccontextmanager
async def database():
    url = os.environ.get("SEM_ALERT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires disposable SEM_ALERT_TEST_DATABASE_URL")
    parsed = make_url(url)
    assert parsed.drivername == "postgresql+asyncpg"
    assert parsed.host in {"localhost", "127.0.0.1"}
    assert parsed.database == "sem_writeback_test"
    schema = "sem_nonfunds_test_" + uuid4().hex
    engine = create_async_engine(
        url,
        connect_args={"server_settings": {"statement_timeout": "5000"}},
        execution_options={"schema_translate_map": {None: schema}},
    )
    created = False
    try:
        async with engine.begin() as conn:
            await conn.execute(CreateSchema(schema))
            metadata = MetaData()
            for model in (BaiduAccount, Campaign, WritebackAction):
                table = model.__table__.to_metadata(metadata)
                for constraint in list(table.constraints):
                    if isinstance(constraint, ForeignKeyConstraint):
                        table.constraints.remove(constraint)
            await conn.run_sync(metadata.create_all)
        created = True
        yield engine
    finally:
        if created:
            assert schema.startswith("sem_nonfunds_test_") and len(schema) == 50
            async with engine.begin() as conn:
                await conn.execute(DropSchema(schema, cascade=True))
        await engine.dispose()


def account_row() -> BaiduAccount:
    return BaiduAccount(
        id=17,
        tenant_id=3,
        baidu_username="disposable-test",
        baidu_ucid=1700,
        access_token_encrypted="test",
        expires_at=datetime(2099, 1, 1),
        status="active",
    )


def campaign_row() -> Campaign:
    return Campaign(
        id=101,
        tenant_id=3,
        baidu_account_id=17,
        campaign_id=202,
        campaign_name="disposable-test",
        pause=False,
        schedule_price_factors=[],
    )


def action_row(action_type: str = "campaign_schedule") -> WritebackAction:
    return WritebackAction(
        tenant_id=3,
        baidu_account_id=17,
        action_type=action_type,
        word="disposable-test",
        campaign_id=202,
        dry_run=False,
        status="pending",
    )


def test_reconciled_intent_cannot_resume_after_commit_gap():
    async def exercise():
        async with database() as engine:
            async with AsyncSession(engine, expire_on_commit=False) as setup:
                account = account_row()
                campaign = campaign_row()
                record = action_row("campaign_pause")
                setup.add_all([account, campaign, record])
                await setup.commit()
                record_id = record.id

            async with AsyncSession(engine, expire_on_commit=False) as reconciler:
                record = await reconciler.get(WritebackAction, record_id, with_for_update=True)
                record.status = "failed"
                record.reconciliation_result = "confirmed_not_executed"
                await reconciler.commit()

            async with AsyncSession(engine, expire_on_commit=False) as executor:
                account = await executor.get(BaiduAccount, 17)
                campaign = await executor.get(Campaign, 101)
                record = await executor.get(WritebackAction, record_id)
                with pytest.raises(WritebackError, match="已被处理"):
                    await _relock_action_intent(
                        executor, record, asset=campaign, account=account
                    )
                await executor.rollback()

            async with AsyncSession(engine) as check:
                record = await check.get(WritebackAction, record_id)
                assert record.status == "failed"
                assert record.reconciliation_result == "confirmed_not_executed"

    asyncio.run(exercise())


def test_schedule_intent_blocks_concurrent_campaign_pause_domain():
    async def exercise():
        async with database() as engine:
            async with AsyncSession(engine, expire_on_commit=False) as first:
                first.add_all([account_row(), campaign_row(), action_row()])
                await first.commit()

            async with AsyncSession(engine, expire_on_commit=False) as second:
                campaign = await second.scalar(
                    select(Campaign).where(Campaign.id == 101).with_for_update()
                )
                assert campaign is not None
                with pytest.raises(WritebackError, match="未完成或待人工对账"):
                    await _ensure_no_unresolved_funds_writeback(
                        second,
                        WritebackAction,
                        WritebackAction.tenant_id == 3,
                        WritebackAction.campaign_id == 202,
                        WritebackAction.action_type.in_(CAMPAIGN_PAUSE_CONFLICT_ACTIONS),
                    )
                await second.rollback()

    asyncio.run(exercise())
