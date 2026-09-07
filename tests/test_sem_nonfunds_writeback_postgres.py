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
    apply_match_type_writeback,
    apply_negative_batch_writeback,
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


def keyword_row() -> Keyword:
    return Keyword(
        id=401,
        tenant_id=3,
        baidu_account_id=17,
        keyword_id=404,
        keyword="工业泵",
        campaign_id=202,
        adgroup_id=303,
        match_type=1,
        phrase_type=1,
        pause=False,
        total_impression=0,
        category_source="auto",
    )


def test_reconciler_wins_during_commit_relock_gap_and_executor_stays_stopped():
    async def exercise():
        async with database() as engine:
            async with AsyncSession(engine, expire_on_commit=False) as setup:
                setup.add_all([account_row(), campaign_row(), adgroup_row()])
                await setup.commit()

            intent_committed = asyncio.Event()
            reconciliation_finished = asyncio.Event()
            remote = AsyncMock()

            async def persist_with_reconciliation_gap(
                session, record, *, dry_run, asset, account
            ):
                await _persist_funds_intent(session, record, dry_run=dry_run)
                intent_committed.set()
                await asyncio.wait_for(reconciliation_finished.wait(), 5)
                await _relock_action_intent(
                    session, record, asset=asset, account=account
                )

            async def reconcile_pending_intent():
                await asyncio.wait_for(intent_committed.wait(), 5)
                async with AsyncSession(engine, expire_on_commit=False) as reconciler:
                    record = await reconciler.scalar(
                        select(WritebackAction).with_for_update()
                    )
                    assert record is not None
                    assert record.status == "pending"
                    record.status = "failed"
                    record.reconciliation_result = "confirmed_not_executed"
                    record.error_msg = "manual reconciliation preserved"
                    await reconciler.commit()
                reconciliation_finished.set()

            async with AsyncSession(engine, expire_on_commit=False) as executor:
                reconcile_task = asyncio.create_task(reconcile_pending_intent())
                with (
                    patch(
                        "app.baidu.writeback._persist_action_intent",
                        new=persist_with_reconciliation_gap,
                    ),
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
                    with pytest.raises(WritebackError, match="已被处理"):
                        await apply_negative_writeback(
                            executor,
                            3,
                            "工业泵",
                            303,
                            match_mode="phrase",
                            operator_user_id=9,
                            operator_name="tester",
                        )
                await asyncio.wait_for(reconcile_task, 5)

            remote.assert_not_awaited()
            async with AsyncSession(engine) as check:
                record = await check.scalar(select(WritebackAction))
                assert record.status == "failed"
                assert record.reconciliation_result == "confirmed_not_executed"
                assert record.error_msg == "manual reconciliation preserved"

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
                        dry_run=False,
                        exclude_record_id=own.id,
                    )

    asyncio.run(exercise())


def test_two_live_add_word_attempts_from_empty_state_call_remote_once():
    async def exercise():
        async with database() as engine:
            async with AsyncSession(engine, expire_on_commit=False) as setup:
                setup.add_all([account_row(), campaign_row(), adgroup_row()])
                await setup.commit()

            first_remote_started = asyncio.Event()
            release_first_remote = asyncio.Event()
            second_started = asyncio.Event()
            remote_calls = 0

            async def remote(*args, **kwargs):
                nonlocal remote_calls
                remote_calls += 1
                first_remote_started.set()
                await asyncio.wait_for(release_first_remote.wait(), 5)
                return {"header": {"status": 0}}

            settings = SimpleNamespace(
                baidu_write_dry_run=False,
                baidu_write_is_dry_run=lambda tenant_id, account_id, scope: False,
            )

            async def run_attempt(mark_started=False):
                async with AsyncSession(engine, expire_on_commit=False) as session:
                    if mark_started:
                        second_started.set()
                    return await apply_add_word_writeback(
                        session,
                        3,
                        "工业泵",
                        303,
                        price=3.6,
                        match_mode="exact",
                        operator_user_id=9,
                        operator_name="tester",
                    )

            with (
                patch("app.baidu.writeback._account_client", return_value=object()),
                patch("app.baidu.writeback.KeywordService.add_word", new=remote),
                patch("app.baidu.writeback.get_settings", return_value=settings),
            ):
                first = asyncio.create_task(run_attempt())
                await asyncio.wait_for(first_remote_started.wait(), 5)
                second = asyncio.create_task(run_attempt(mark_started=True))
                await asyncio.wait_for(second_started.wait(), 5)
                done, _ = await asyncio.wait({second}, timeout=0.2)
                assert not done, "second addWord must wait for the adgroup row lock"
                release_first_remote.set()
                first_result = await asyncio.wait_for(first, 5)
                assert first_result.status == "success"
                with pytest.raises(WritebackError, match="近期成功"):
                    await asyncio.wait_for(second, 5)

            assert remote_calls == 1
            async with AsyncSession(engine) as check:
                records = (await check.scalars(select(WritebackAction))).all()
                assert len(records) == 1
                assert records[0].status == "success"

    asyncio.run(exercise())


def test_match_combo_sync_in_commit_relock_gap_blocks_remote_overwrite():
    async def exercise():
        async with database() as engine:
            async with AsyncSession(engine, expire_on_commit=False) as setup:
                setup.add_all([account_row(), campaign_row(), adgroup_row(), keyword_row()])
                await setup.commit()

            intent_committed = asyncio.Event()
            sync_finished = asyncio.Event()
            remote = AsyncMock()

            async def persist_with_gap(session, record, *, dry_run, asset, account):
                await _persist_funds_intent(session, record, dry_run=dry_run)
                intent_committed.set()
                await asyncio.wait_for(sync_finished.wait(), 5)
                await _relock_action_intent(session, record, asset=asset, account=account)

            async def sync_match_combo():
                await asyncio.wait_for(intent_committed.wait(), 5)
                async with AsyncSession(engine, expire_on_commit=False) as sync_session:
                    row = await sync_session.scalar(
                        select(Keyword).where(Keyword.id == 401).with_for_update()
                    )
                    row.match_type = 2
                    row.phrase_type = 1
                    await sync_session.commit()
                sync_finished.set()

            async with AsyncSession(engine, expire_on_commit=False) as executor:
                sync_task = asyncio.create_task(sync_match_combo())
                with (
                    patch("app.baidu.writeback._persist_action_intent", new=persist_with_gap),
                    patch("app.baidu.writeback._account_client", return_value=object()),
                    patch("app.baidu.writeback.KeywordService.update_word_match_type", remote),
                    patch(
                        "app.baidu.writeback.get_settings",
                        return_value=SimpleNamespace(
                            baidu_write_dry_run=False,
                            baidu_write_is_dry_run=lambda tenant_id, account_id, scope: False,
                        ),
                    ),
                ):
                    with pytest.raises(WritebackError, match="关键词匹配模式已变化"):
                        await apply_match_type_writeback(
                            executor,
                            3,
                            404,
                            2,
                            3,
                            operator_user_id=9,
                            operator_name="tester",
                        )
                await asyncio.wait_for(sync_task, 5)

            remote.assert_not_awaited()
            async with AsyncSession(engine) as check:
                record = await check.scalar(select(WritebackAction))
                keyword = await check.get(Keyword, 401)
                assert record.status == "failed"
                assert record.old_value == 1
                assert (keyword.match_type, keyword.phrase_type) == (2, 1)

    asyncio.run(exercise())


def test_dry_run_add_word_does_not_block_later_live_request():
    async def exercise():
        async with database() as engine:
            async with AsyncSession(engine, expire_on_commit=False) as setup:
                setup.add_all([account_row(), campaign_row(), adgroup_row()])
                rehearsal = action_row("add_word")
                rehearsal.adgroup_id = 303
                rehearsal.word = "工业泵"
                rehearsal.dry_run = True
                rehearsal.status = "dry_run"
                setup.add(rehearsal)
                await setup.commit()

            remote = AsyncMock(return_value={"header": {"status": 0}})
            async with AsyncSession(engine, expire_on_commit=False) as executor:
                with (
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
                    result = await apply_add_word_writeback(
                        executor,
                        3,
                        "工业泵",
                        303,
                        price=3.6,
                        match_mode="exact",
                        operator_user_id=9,
                        operator_name="tester",
                    )
                    assert result.status == "success"

            remote.assert_awaited_once()
            async with AsyncSession(engine) as check:
                rows = (await check.scalars(
                    select(WritebackAction).order_by(WritebackAction.id)
                )).all()
                assert [(row.dry_run, row.status) for row in rows] == [
                    (True, "dry_run"),
                    (False, "success"),
                ]

    asyncio.run(exercise())


def test_batch_negative_recomputes_from_latest_list_after_intent_commit():
    async def exercise():
        async with database() as engine:
            async with AsyncSession(engine, expire_on_commit=False) as setup:
                setup.add_all([account_row(), campaign_row(), adgroup_row()])
                await setup.commit()

            relock_entered = asyncio.Event()
            sync_finished = asyncio.Event()
            original_relock = _relock_action_intent
            remote = AsyncMock(return_value={"header": {"status": 0}})

            async def relock_after_sync(session, record, **kwargs):
                relock_entered.set()
                await asyncio.wait_for(sync_finished.wait(), 5)
                await original_relock(session, record, **kwargs)

            async def sync_latest_list():
                await asyncio.wait_for(relock_entered.wait(), 5)
                async with AsyncSession(engine, expire_on_commit=False) as sync_session:
                    row = await sync_session.scalar(
                        select(Adgroup).where(Adgroup.id == 301).with_for_update()
                    )
                    row.negative_words = ["已同步词"]
                    await sync_session.commit()
                sync_finished.set()

            async with AsyncSession(engine, expire_on_commit=False) as executor:
                sync_task = asyncio.create_task(sync_latest_list())
                with (
                    patch("app.baidu.writeback._relock_action_intent", new=relock_after_sync),
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
                    results = await apply_negative_batch_writeback(
                        executor,
                        3,
                        ["工业泵", "阀门"],
                        303,
                        match_mode="phrase",
                        operator_user_id=9,
                        operator_name="tester",
                    )
                await asyncio.wait_for(sync_task, 5)
                assert [result.status for result in results] == ["success", "success"]

            remote.assert_awaited_once_with(
                303, negative_words=["已同步词", "工业泵", "阀门"]
            )
            async with AsyncSession(engine) as check:
                adgroup = await check.get(Adgroup, 301)
                assert adgroup.negative_words == ["已同步词", "工业泵", "阀门"]
                statuses = (await check.scalars(select(WritebackAction.status))).all()
                assert statuses == ["success", "success"]

    asyncio.run(exercise())
