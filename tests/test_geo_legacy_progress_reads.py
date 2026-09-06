"""Legacy progress GETs observe timeouts while background workers own writes."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.geo.content import async_jobs, patrol, routes
from app.geo.read_session import geo_read_session
from app.geo.tenant_scope import require_geo_read_entitlement


def _route(path):
    return next(
        route
        for route in routes.router.routes
        if route.path == path and route.methods == {"GET"}
    )


def _job(status="running"):
    old = datetime.utcnow() - timedelta(days=1)
    return SimpleNamespace(
        id=9,
        tenant_id=1,
        kind=async_jobs.KIND_GENERATE,
        status=status,
        ref_type="content_task",
        ref_id=14,
        request_meta={"progress": {"message": "处理中", "pct": 45}},
        result_meta=None,
        error=None,
        created_by=1,
        created_at=old,
        started_at=old if status == "running" else None,
        finished_at=None,
    )


def _patrol(status="running"):
    old = datetime.utcnow() - timedelta(days=1)
    return SimpleNamespace(
        id=7,
        tenant_id=1,
        status=status,
        trigger="manual",
        auto_persist=True,
        prefer_real=True,
        prompt_limit=10,
        engine_keys=["deepseek"],
        summary=None,
        items=None,
        error=None,
        started_at=old if status == "running" else None,
        finished_at=None,
        created_by=1,
        created_at=old,
    )


def test_legacy_progress_gets_use_read_only_session_and_entitlement():
    for path in {
        "/async-jobs",
        "/async-jobs/{job_id}",
        "/visibility-patrol/runs",
        "/visibility-patrol/runs/{run_id}",
    }:
        route = _route(path)
        calls = {dependency.call for dependency in route.dependant.dependencies}
        assert geo_read_session in calls, path
        assert require_geo_read_entitlement in calls, path


def test_legacy_async_get_reports_stored_timeout_without_writing():
    async def scenario():
        row = _job()
        session = Mock(get=AsyncMock(return_value=row), commit=AsyncMock())
        result = await routes.get_async_job(9, 1, Mock(), session)
        assert result["status"] == result["stored_status"] == "running"
        assert result["stale"]
        assert result["stale_reason"] == "elapsed_threshold_exceeded"
        assert result["reconciliation"] == "background"
        session.commit.assert_not_awaited()

    asyncio.run(scenario())


def test_legacy_async_list_does_not_release_tasks_or_reconcile_jobs():
    async def scenario():
        session = Mock(scalars=AsyncMock(return_value=[_job()]), commit=AsyncMock())
        with (
            patch.object(
                async_jobs,
                "reconcile_stale_job",
                side_effect=AssertionError("GET must not reconcile"),
            ),
            patch.object(
                async_jobs,
                "reconcile_stale_content_tasks",
                side_effect=AssertionError("GET must not release tasks"),
            ),
        ):
            result = await routes.list_async_jobs(1, None, None, 20, Mock(), session)
        assert result["items"][0]["stale"]
        assert result["stale_tasks_released"] == 0
        session.commit.assert_not_awaited()

    asyncio.run(scenario())


def test_legacy_patrol_list_reports_stored_timeout_without_writing():
    async def scenario():
        session = Mock(scalars=AsyncMock(return_value=[_patrol()]), commit=AsyncMock())
        with patch.object(
            patrol,
            "reconcile_stale_patrol_run",
            side_effect=AssertionError("GET must not reconcile"),
        ):
            result = await routes.list_visibility_patrol_runs(1, 20, Mock(), session)
        item = result["items"][0]
        assert item["status"] == item["stored_status"] == "running"
        assert item["stale"] and item["reconciliation"] == "background"
        session.commit.assert_not_awaited()

    asyncio.run(scenario())


def test_live_patrol_lock_prevents_timeout_reconciliation():
    async def scenario():
        @asynccontextmanager
        async def busy(_run_id):
            yield False

        row = _patrol()
        row.summary = {"execution_protocol": patrol.PATROL_EXECUTION_PROTOCOL}
        session = Mock(refresh=AsyncMock(), commit=AsyncMock())
        with patch.object(patrol, "patrol_execution_lock", busy):
            result = await patrol.reconcile_stale_patrol_run(session, row)
        assert result.status == "running"
        session.refresh.assert_not_awaited()
        session.commit.assert_not_awaited()

    asyncio.run(scenario())


def test_patrol_execution_lock_releases_after_worker_failure():
    async def scenario():
        connection = Mock(
            scalar=AsyncMock(return_value=True),
            execute=AsyncMock(),
            commit=AsyncMock(),
            invalidate=AsyncMock(),
        )

        @asynccontextmanager
        async def connect():
            yield connection

        with patch("app.database.engine", SimpleNamespace(connect=connect)):
            try:
                async with patrol.patrol_execution_lock(7) as acquired:
                    assert acquired
                    raise RuntimeError("worker failed")
            except RuntimeError:
                pass
        assert "pg_advisory_unlock" in str(connection.execute.await_args.args[0])
        assert connection.commit.await_count == 2

    asyncio.run(scenario())


def test_background_tick_persists_both_reconcilers():
    async def scenario():
        from app.geo.content import geo_scheduler

        with (
            patch.object(
                async_jobs,
                "reconcile_stale_jobs_background",
                AsyncMock(return_value={"failed_jobs": 1, "released_tasks": 1}),
            ) as jobs,
            patch.object(
                patrol,
                "reconcile_stale_patrol_runs_background",
                AsyncMock(return_value={"failed_runs": 1}),
            ) as patrols,
        ):
            await geo_scheduler.run_geo_stale_reconciliation()
        jobs.assert_awaited_once()
        patrols.assert_awaited_once()

    asyncio.run(scenario())


def test_orphan_task_recovery_only_accepts_content_generation_jobs_as_live():
    async def scenario():
        task = SimpleNamespace(id=14, status="generating")
        session = Mock(
            scalars=AsyncMock(return_value=[task]),
            scalar=AsyncMock(return_value=None),
            commit=AsyncMock(),
        )
        released = await async_jobs.reconcile_stale_content_tasks(
            session, tenant_id=1, max_age_seconds=60
        )
        assert released == 1 and task.status == "editing"
        statement = session.scalar.await_args.args[0]
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert "ref_type IS NULL" in sql
        assert "ref_type = 'content_task'" in sql
        assert "kind IN ('generate_article', 'create_variants')" in sql
        session.commit.assert_awaited_once()

    asyncio.run(scenario())


def test_patrol_startup_fails_owned_interrupted_run_without_requeueing_pending():
    async def scenario():
        running = _patrol("running")
        running.summary = {"execution_protocol": patrol.PATROL_EXECUTION_PROTOCOL}
        pending = _patrol("pending")
        pending.id = 8
        pending.created_at = datetime.utcnow()
        session = Mock(
            scalars=AsyncMock(return_value=[running, pending]),
            refresh=AsyncMock(),
            get=AsyncMock(side_effect=lambda _model, run_id: running if run_id == 7 else pending),
            commit=AsyncMock(),
        )

        @asynccontextmanager
        async def factory():
            yield session

        @asynccontextmanager
        async def available(_run_id):
            yield True

        with (
            patch("app.database.async_session_factory", factory),
            patch.object(patrol, "patrol_execution_lock", available),
        ):
            stats = await patrol.recover_patrol_runs_on_startup()
        assert running.status == "failed"
        assert stats == {
            "failed_running": 1,
            "failed_stale_pending": 0,
            "pending_deferred": 1,
            "legacy_running_deferred": 0,
        }

    asyncio.run(scenario())


def test_legacy_running_patrol_is_reported_stale_but_never_auto_failed():
    async def scenario():
        row = _patrol("running")
        session = Mock(refresh=AsyncMock(), commit=AsyncMock())

        @asynccontextmanager
        async def forbidden(_run_id):
            raise AssertionError("legacy worker does not share the advisory protocol")
            yield

        with patch.object(patrol, "patrol_execution_lock", forbidden):
            result = await patrol.reconcile_stale_patrol_run(session, row)
        assert result.status == "running"
        assert patrol.patrol_read_payload(row)["stale"]
        session.refresh.assert_not_awaited()
        session.commit.assert_not_awaited()

    asyncio.run(scenario())


def test_owned_patrol_wrapper_is_the_only_marker_entry_point():
    async def scenario():
        row = _patrol("pending")
        session = Mock()

        @asynccontextmanager
        async def available(_run_id):
            yield True

        execute = AsyncMock(return_value=row)
        with (
            patch.object(patrol, "patrol_execution_lock", available),
            patch.object(patrol, "execute_patrol_run", execute),
        ):
            assert await patrol.execute_patrol_run_owned(session, row.id) is row
        execute.assert_awaited_once_with(
            session,
            row.id,
            execution_protocol=patrol.PATROL_EXECUTION_PROTOCOL,
        )

    asyncio.run(scenario())
