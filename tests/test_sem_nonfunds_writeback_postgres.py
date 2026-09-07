"""Native PostgreSQL checks for non-funds writeback intent races."""
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
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
    _ensure_add_word_not_duplicate,
    _persist_funds_intent,
    _relock_action_intent,
    apply_add_word_writeback,
    apply_negative_writeback,
)
from app.models import Adgroup, BaiduAccount, Campaign, Keyword, WritebackAction


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
            for model in (BaiduAccount, Campaign, Adgroup, Keyword, WritebackAction):
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


def adgroup_row() -> Adgroup:
    return Adgroup(
        id=301,
        tenant_id=3,
        baidu_account_id=17,
        adgroup_id=303,
        campaign_id=202,
        adgroup_name="disposable-test",
        negative_words=[],
        exact_negative_words=[],
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
            async with AsyncSession(engine, expire_on_commit=False) as setup:
                setup.add_all([account_row(), campaign_row()])
                await setup.commit()

            async with AsyncSession(engine, expire_on_commit=False) as first, \
                       AsyncSession(engine, expire_on_commit=False) as second:
                campaign = await first.scalar(
                    select(Campaign).where(Campaign.id == 101).with_for_update()
                )
                assert campaign is not None
                await _ensure_no_unresolved_funds_writeback(
                    first,
                    WritebackAction,
                    WritebackAction.tenant_id == 3,
                    WritebackAction.campaign_id == 202,
                    WritebackAction.action_type.in_(CAMPAIGN_PAUSE_CONFLICT_ACTIONS),
                )

                started = asyncio.Event()

                async def contender():
                    started.set()
                    locked = await second.scalar(
                        select(Campaign).where(Campaign.id == 101).with_for_update()
                    )
                    assert locked is not None
                    try:
                        await _ensure_no_unresolved_funds_writeback(
                            second,
                            WritebackAction,
                            WritebackAction.tenant_id == 3,
                            WritebackAction.campaign_id == 202,
                            WritebackAction.action_type.in_(CAMPAIGN_PAUSE_CONFLICT_ACTIONS),
                        )
                    except WritebackError:
                        await second.rollback()
                        return "blocked"
                    raise AssertionError("campaign pause must not pass the schedule intent")

                task = asyncio.create_task(contender())
                await started.wait()
                done, _ = await asyncio.wait({task}, timeout=0.2)
                assert not done, "second session must wait for the campaign row lock"
                first.add(action_row())
                await first.commit()
                assert await asyncio.wait_for(task, 5) == "blocked"

    asyncio.run(exercise())


def test_full_list_sync_in_commit_relock_gap_blocks_stale_remote_overwrite():
    async def exercise():
        async with database() as engine:
            async with AsyncSession(engine, expire_on_commit=False) as setup:
                setup.add_all([account_row(), campaign_row(), adgroup_row()])
                await setup.commit()

            intent_committed = asyncio.Event()
            sync_finished = asyncio.Event()
            remote = AsyncMock()

            async def persist_with_gap(session, record, *, dry_run, asset, account):
                await _persist_funds_intent(session, record, dry_run=dry_run)
                intent_committed.set()
                await asyncio.wait_for(sync_finished.wait(), 5)
                await _relock_action_intent(session, record, asset=asset, account=account)

            async def sync_snapshot():
                await intent_committed.wait()
                async with AsyncSession(engine, expire_on_commit=False) as sync_session:
                    row = await sync_session.scalar(
                        select(Adgroup).where(Adgroup.id == 301).with_for_update()
                    )
                    row.negative_words = ["工业泵"]
                    await sync_session.commit()
                sync_finished.set()

            async with AsyncSession(engine, expire_on_commit=False) as executor:
                sync_task = asyncio.create_task(sync_snapshot())
                with (
                    patch("app.baidu.writeback._persist_action_intent", new=persist_with_gap),
                    patch("app.baidu.writeback._account_client", return_value=object()),
                    patch("app.baidu.writeback.AdgroupService.update_negative_words", remote),
                    patch(
                        "app.baidu.writeback.get_settings",
                        return_value=SimpleNamespace(
                            baidu_write_dry_run=False,
                            baidu_write_is_dry_run=lambda tenant_id, account_id, scope: False,
                        ),
                    ),
                ):
                    with pytest.raises(WritebackError, match="否词列表已变化"):
                        await apply_negative_writeback(
                            executor,
                            3,
                            "工业泵",
                            303,
                            match_mode="phrase",
                            operator_user_id=9,
                            operator_name="tester",
                        )
                await asyncio.wait_for(sync_task, 5)

            remote.assert_not_awaited()
            async with AsyncSession(engine) as check:
                record = await check.scalar(select(WritebackAction))
                adgroup = await check.get(Adgroup, 301)
                assert record.status == "failed"
                assert adgroup.negative_words == ["工业泵"]

    asyncio.run(exercise())


def test_add_word_success_in_commit_relock_gap_blocks_duplicate_remote_call():
    async def exercise():
        async with database() as engine:
            async with AsyncSession(engine, expire_on_commit=False) as setup:
                setup.add_all([account_row(), campaign_row(), adgroup_row()])
                await setup.commit()

            intent_committed = asyncio.Event()
            duplicate_finished = asyncio.Event()
            remote = AsyncMock()

            async def persist_with_gap(session, record, *, dry_run, asset, account):
                await _persist_funds_intent(session, record, dry_run=dry_run)
                intent_committed.set()
                await asyncio.wait_for(duplicate_finished.wait(), 5)
                await _relock_action_intent(session, record, asset=asset, account=account)

            async def insert_success():
                await intent_committed.wait()
                async with AsyncSession(engine, expire_on_commit=False) as other:
                    duplicate = action_row("add_word")
                    duplicate.adgroup_id = 303
                    duplicate.word = "工业泵"
                    duplicate.status = "success"
                    other.add(duplicate)
                    await other.commit()
                duplicate_finished.set()

            async with AsyncSession(engine, expire_on_commit=False) as executor:
                duplicate_task = asyncio.create_task(insert_success())
                with (
                    patch("app.baidu.writeback._persist_action_intent", new=persist_with_gap),
                    patch("app.baidu.writeback._account_client", return_value=object()),
                    patch("app.baidu.writeback.KeywordService.add_word", remote),
                    patch(
                        "app.baidu.writeback.get_settings",
                        return_value=SimpleNamespace(
                            baidu_write_dry_run=False,
                            baidu_write_is_dry_run=lambda tenant_id, account_id, scope: False,
                        ),
                    ),
                ):
                    with pytest.raises(WritebackError, match="近期成功"):
                        await apply_add_word_writeback(
                            executor,
                            3,
                            "工业泵",
                            303,
                            price=3.6,
                            match_mode="exact",
                            operator_user_id=9,
                            operator_name="tester",
                        )
                await asyncio.wait_for(duplicate_task, 5)

            remote.assert_not_awaited()
            async with AsyncSession(engine) as check:
                statuses = (await check.scalars(
                    select(WritebackAction.status).order_by(WritebackAction.id)
                )).all()
                assert statuses == ["failed", "success"]

    asyncio.run(exercise())


def test_add_word_recheck_sees_other_session_success_before_remote_call():
    async def exercise():
        async with database() as engine:
            async with AsyncSession(engine, expire_on_commit=False) as first:
                first.add_all([account_row(), campaign_row()])
                own = action_row("add_word")
                own.adgroup_id = 303
                own.word = "工业泵"
                first.add(own)
                await first.commit()

            async with AsyncSession(engine, expire_on_commit=False) as second:
                duplicate = action_row("add_word")
                duplicate.adgroup_id = 303
                duplicate.word = "工业泵"
                duplicate.status = "success"
                second.add(duplicate)
                await second.commit()

            async with AsyncSession(engine) as executor:
                with pytest.raises(WritebackError, match="近期成功"):
                    await _ensure_add_word_not_duplicate(
                        executor,
                        tenant_id=3,
                        adgroup_id=303,
                        word="工业泵",
                        exclude_record_id=own.id,
                    )

    asyncio.run(exercise())
