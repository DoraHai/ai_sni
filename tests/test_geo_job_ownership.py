"""Offline ownership/claim regressions. Real PostgreSQL validation is separate."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from app.geo.content import async_jobs as jobs


def test_two_dispatches_execute_once():
    async def scenario():
        held = set()
        entered, finish = asyncio.Event(), asyncio.Event()

        @asynccontextmanager
        async def lock(job_id):
            if job_id in held:
                yield None
                return
            held.add(job_id)
            try:
                yield object()
            finally:
                held.remove(job_id)

        async def execute(*args, **kwargs):
            entered.set()
            await finish.wait()

        with patch.object(jobs, 'job_execution_lock', lock), patch.object(
            jobs, '_run_owned_job', new=AsyncMock(side_effect=execute)
        ) as run:
            first = asyncio.create_task(jobs.run_job_in_background(1))
            await entered.wait()
            await jobs.run_job_in_background(1)
            finish.set()
            await first
            assert run.await_count == 1
            assert not held
    asyncio.run(scenario())


def test_live_job_not_reconciled_even_when_old():
    async def scenario():
        @asynccontextmanager
        async def busy(job_id):
            yield None
        row = SimpleNamespace(
            id=1,
            status='running',
            started_at=datetime.utcnow()-timedelta(days=1),
            request_meta={'execution_protocol': jobs.JOB_EXECUTION_PROTOCOL},
        )
        session = SimpleNamespace(refresh=AsyncMock(), commit=AsyncMock())
        with patch.object(jobs, 'job_execution_lock', busy):
            assert await jobs.reconcile_stale_job(session, row) is row
        assert row.status == 'running'
        session.commit.assert_not_awaited()
    asyncio.run(scenario())


def test_startup_skips_job_owned_by_another_worker():
    async def scenario():
        @asynccontextmanager
        async def busy(job_id):
            yield None
        row = SimpleNamespace(id=1, status='running')
        session = SimpleNamespace(scalars=AsyncMock(side_effect=[[row], []]), refresh=AsyncMock(), commit=AsyncMock())
        @asynccontextmanager
        async def factory():
            yield session
        with patch.object(jobs, 'job_execution_lock', busy), patch('app.database.async_session_factory', factory):
            stats = await jobs.recover_jobs_on_startup()
        assert not any(stats.values())
        assert row.status == 'running'
        session.refresh.assert_not_awaited()
    asyncio.run(scenario())


def test_interrupted_running_job_is_failed_not_replayed():
    async def scenario():
        row = SimpleNamespace(
            id=1,
            status='running',
            ref_id=None,
            request_meta={'execution_protocol': jobs.JOB_EXECUTION_PROTOCOL},
        )
        session = SimpleNamespace(commit=AsyncMock())
        stats = dict(
            failed_running=0,
            failed_stale_pending=0,
            requeued=0,
            legacy_running_deferred=0,
        )
        queue = []
        await jobs._recover_unowned_job(session, row, 120, True, stats, queue)
        assert row.status == 'failed'
        assert stats['failed_running'] == 1
        assert queue == []
    asyncio.run(scenario())


def test_legacy_running_job_is_never_auto_failed():
    async def scenario():
        row = SimpleNamespace(
            id=1,
            status='running',
            request_meta={},
            started_at=datetime.utcnow() - timedelta(days=1),
        )
        session = SimpleNamespace(refresh=AsyncMock(), commit=AsyncMock())
        assert await jobs.reconcile_stale_job(session, row) is row
        assert row.status == 'running'
        session.refresh.assert_not_awaited()
        session.commit.assert_not_awaited()

    asyncio.run(scenario())


def test_startup_defers_legacy_running_job():
    async def scenario():
        row = SimpleNamespace(id=1, status='running', request_meta={})
        session = SimpleNamespace(
            scalars=AsyncMock(side_effect=[[row], []]),
            refresh=AsyncMock(),
            commit=AsyncMock(),
        )

        @asynccontextmanager
        async def available(_job_id):
            yield object()

        @asynccontextmanager
        async def factory():
            yield session

        with (
            patch.object(jobs, 'job_execution_lock', available),
            patch('app.database.async_session_factory', factory),
        ):
            stats = await jobs.recover_jobs_on_startup()
        assert row.status == 'running'
        assert stats['legacy_running_deferred'] == 1

    asyncio.run(scenario())


def test_unclaimed_job_never_executes_and_claim_is_conditional():
    async def scenario():
        session = SimpleNamespace(scalar=AsyncMock(return_value=None), commit=AsyncMock(), get=AsyncMock())
        @asynccontextmanager
        async def factory(**kwargs):
            yield session
        with patch('app.database.async_session_factory', factory):
            await jobs._run_owned_job(42)
        session.get.assert_not_awaited()
        statement = session.scalar.await_args.args[0]
        compiled = statement.compile(dialect=postgresql.dialect())
        assert 'RETURNING geo_async_jobs.id' in str(compiled)
        assert 'geo_async_jobs.status =' in str(compiled)
        assert 'pending' in compiled.params.values()
        assert 42 in compiled.params.values()
    asyncio.run(scenario())


def test_claimed_job_persists_new_execution_protocol():
    async def scenario():
        row = SimpleNamespace(
            id=42,
            kind=jobs.KIND_GENERATE,
            status='running',
            request_meta={},
            ref_id=None,
            started_at=None,
            finished_at=None,
            error=None,
            result_meta=None,
        )
        session = SimpleNamespace(
            scalar=AsyncMock(return_value=42),
            commit=AsyncMock(),
            get=AsyncMock(return_value=row),
        )

        @asynccontextmanager
        async def factory(**kwargs):
            yield session

        with (
            patch('app.database.async_session_factory', factory),
            patch.object(jobs, '_execute_generate', AsyncMock(return_value={'ok': True})),
        ):
            await jobs._run_owned_job(42)
        assert row.request_meta['execution_protocol'] == jobs.JOB_EXECUTION_PROTOCOL
        assert row.status == 'succeeded'

    asyncio.run(scenario())


@pytest.mark.parametrize('unlock_fails', [False, True])
def test_advisory_lock_cleanup_on_worker_error(unlock_fails):
    async def scenario():
        conn = SimpleNamespace(scalar=AsyncMock(return_value=True), execute=AsyncMock(), commit=AsyncMock(), invalidate=AsyncMock())
        if unlock_fails:
            conn.execute.side_effect = RuntimeError('disconnect')
        @asynccontextmanager
        async def connect():
            yield conn
        with patch('app.database.engine', SimpleNamespace(connect=connect)):
            with pytest.raises(RuntimeError):
                async with jobs.job_execution_lock(42) as owned:
                    assert owned is conn
                    raise RuntimeError('worker failed')
        assert 'pg_advisory_unlock' in str(conn.execute.await_args.args[0])
        assert conn.invalidate.await_count == int(unlock_fails)
    asyncio.run(scenario())
