"""Opt-in isolated PostgreSQL test, no migrations and no production URLs."""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import test_writeback_approval  # noqa: F401
from sqlalchemy import Column, Integer, MetaData, Table, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import sem_tasks as api
from app.models.sem_task import SemTask
from test_sem_tasks import context, evidence


def test_native_task_constraints_lifecycle_and_concurrent_verify():
    url = os.getenv("SEM_TASK_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires dedicated local sem_tasks_test database")
    parsed = make_url(url)
    assert parsed.drivername == "postgresql+asyncpg"
    assert parsed.host in {"127.0.0.1", "localhost"} and parsed.database == "sem_tasks_test"
    assert not parsed.query  # No alternate host/service routing.
    schema = "sem_tasks_test_" + uuid.uuid4().hex

    async def run():
        admin = create_async_engine(url, poolclass=NullPool)
        engine = create_async_engine(url, poolclass=NullPool,
                                     connect_args={"server_settings": {"search_path": schema}})
        created = False
        try:
            async with admin.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
                created = True
            metadata = MetaData()
            tenant = Table("tenants", metadata, Column("id", Integer, primary_key=True))
            SemTask.__table__.to_metadata(metadata)
            async with engine.begin() as conn:
                await conn.run_sync(metadata.create_all)
                await conn.execute(tenant.insert().values(id=3))
            with patch.object(api, "observation", AsyncMock(return_value=evidence(3))):
                async with AsyncSession(engine, expire_on_commit=False) as session:
                    result = await api.create(api.CreateTask(title="核对审批", params={
                        "metric_key": "sem.approvals.pending_count", "direction": "down", "target_value": 1}),
                        tenant_id=3, ctx=context(), session=session)
                    task_id = result["id"]
                    assert result["created_at"].tzinfo is not None
                    assert result["created_by"] == "user:9"
                    # Deterministic baseline precedes the verified observation.
                    row = await api.load(session, task_id, 3, lock=True)
                    row.baseline_snapshot = evidence(3, datetime.now(timezone.utc)-timedelta(hours=1))
                    await session.commit()

            entered, release = asyncio.Event(), asyncio.Event()
            calls = 0
            async def observe(*args):
                nonlocal calls
                calls += 1
                entered.set()
                await release.wait()
                return evidence(1)

            async def verify():
                async with AsyncSession(engine, expire_on_commit=False) as session:
                    return await api.verify(task_id=task_id, tenant_id=3, ctx=context(), session=session)

            with patch.object(api, "observation", observe):
                first = asyncio.create_task(verify())
                await asyncio.wait_for(entered.wait(), 5)
                second = asyncio.create_task(verify())
                await asyncio.sleep(0.1)
                assert not second.done()
                release.set()
                one, two = await asyncio.wait_for(asyncio.gather(first, second), 10)
                assert one["status"] == two["status"] == "done"
                assert one["completion_evidence"] == two["completion_evidence"]
                assert calls == 1

            from sqlalchemy.exc import IntegrityError
            async with AsyncSession(engine) as session:
                with pytest.raises(IntegrityError):
                    await session.execute(text("UPDATE sem_tasks SET completion_evidence = NULL WHERE id=:id"), {"id": task_id})
                await session.rollback()
                with pytest.raises(IntegrityError):
                    await session.execute(text("DELETE FROM tenants WHERE id=3"))
                await session.rollback()
                assert await session.scalar(select(func.count()).select_from(SemTask)) == 1
                assert (await api.load(session, task_id, 3)).status == "done"
        finally:
            await engine.dispose()
            if created:
                async with admin.begin() as conn:
                    await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin.dispose()
    asyncio.run(run())
