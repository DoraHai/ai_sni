"""Native PostgreSQL locking checks in a dedicated disposable localhost DB only."""
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import ForeignKeyConstraint, MetaData, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from test_sem_foundation_contracts import arguments
from app.baidu import writeback_approval as approvals
from app.models import WritebackApproval


@asynccontextmanager
async def database():
    url = os.environ.get("SEM_FOUNDATION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires disposable SEM_FOUNDATION_TEST_DATABASE_URL")
    parsed = make_url(url)
    assert parsed.drivername == "postgresql+asyncpg"
    assert parsed.host == "127.0.0.1" and parsed.database == "sem_foundation_test"
    schema = "sem_foundation_test_" + uuid4().hex
    engine = create_async_engine(url, connect_args={"server_settings": {"statement_timeout": "5000"}},
                                 execution_options={"schema_translate_map": {None: schema}})
    created = False
    try:
        async with engine.begin() as conn:
            await conn.execute(CreateSchema(schema))
            table = WritebackApproval.__table__.to_metadata(MetaData())
            for constraint in list(table.constraints):
                if isinstance(constraint, ForeignKeyConstraint):
                    table.constraints.remove(constraint)
            await conn.run_sync(table.create)
        created = True
        with patch.object(approvals, "get_settings", return_value=SimpleNamespace(
            baidu_legacy_split_confirmation_enabled=False, baidu_write_confirmation_ttl_minutes=15
        )):
            yield engine
    finally:
        if created:
            # Only the randomly named schema created by this invocation; never public.
            assert schema.startswith("sem_foundation_test_") and len(schema) == 52
            async with engine.begin() as conn:
                await conn.execute(DropSchema(schema, cascade=True))
        await engine.dispose()


async def claim(session, row):
    return await approvals.claim_approval(session, approval_id=row.id, tenant_id=3,
        action_type=row.action_type, payload=row.payload, operator_user_id=9)


@pytest.mark.parametrize("commit_first", [True, False])
def test_native_concurrent_key_waits_for_commit_or_rollback(commit_first):
    async def exercise():
        async with database() as engine:
            async with AsyncSession(engine, expire_on_commit=False) as first, \
                       AsyncSession(engine, expire_on_commit=False) as second:
                row = await approvals.create_self_approved_approval(first, **arguments("sem-native-request-0001"))
                await claim(first, row)
                async def retry():
                    again = await approvals.create_self_approved_approval(second, **arguments("sem-native-request-0001"))
                    try:
                        await claim(second, again)
                        await second.commit()
                        return "consumed"
                    except approvals.WritebackApprovalError:
                        await second.rollback()
                        return "rejected"
                task = asyncio.create_task(retry())
                try:
                    await asyncio.sleep(0.1)
                    assert not task.done(), "second transaction must wait on native advisory lock"
                    if commit_first:
                        await first.commit()
                    else:
                        await first.rollback()
                    assert await asyncio.wait_for(task, 5) == ("rejected" if commit_first else "consumed")
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
            async with AsyncSession(engine) as check:
                assert await check.scalar(select(func.count()).select_from(WritebackApproval)) == 1
                assert (await check.scalar(select(WritebackApproval))).status == "consumed"
    asyncio.run(exercise())


def test_committed_consumption_survives_later_database_failure():
    async def exercise():
        async with database() as engine:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                row = await approvals.create_self_approved_approval(session, **arguments("sem-native-recovery-0001"))
                await claim(session, row)
                await session.commit()
                from sqlalchemy.exc import DBAPIError
                with pytest.raises(DBAPIError):
                    await session.execute(text("SELECT 1 / 0"))
                await session.rollback()
            async with AsyncSession(engine) as retry:
                row = await approvals.create_self_approved_approval(retry, **arguments("sem-native-recovery-0001"))
                with pytest.raises(approvals.WritebackApprovalError, match="已经使用"):
                    await claim(retry, row)
                assert await retry.scalar(select(func.count()).select_from(WritebackApproval)) == 1
    asyncio.run(exercise())


def test_expired_key_cannot_mint_new_approval_and_payload_is_bound():
    async def exercise():
        async with database() as engine:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                row = await approvals.create_self_approved_approval(session, **arguments("sem-native-expiry-0001"))
                row.created_at = approvals.shanghai_now_naive() - timedelta(hours=1)
                await session.commit()
            async with AsyncSession(engine) as retry:
                old = await approvals.create_self_approved_approval(retry, **arguments("sem-native-expiry-0001"))
                assert old.id == row.id
                with pytest.raises(approvals.WritebackApprovalError, match="已过期"):
                    await claim(retry, old)
                changed = arguments("sem-native-expiry-0001")
                changed["payload"] = {"keyword_id": 7, "new_bid": 1.24}
                with pytest.raises(approvals.WritebackApprovalError, match="其他执行参数"):
                    await approvals.create_self_approved_approval(retry, **changed)
                assert await retry.scalar(select(func.count()).select_from(WritebackApproval)) == 1
    asyncio.run(exercise())
