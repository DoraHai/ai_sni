from app.geo.content.geo_scheduler import (
    run_geo_daily_metrics_nightly,
    run_geo_stale_reconciliation,
    run_geo_visibility_patrols,
    scheduler_status,
)


def test_geo_scheduler_exports():
    assert callable(run_geo_daily_metrics_nightly)
    assert callable(run_geo_stale_reconciliation)
    assert callable(run_geo_visibility_patrols)
    assert scheduler_status() in ("stopped", "running", "skipped")


def test_geo_scheduler_keeps_patrol_and_metrics_jobs_isolated():
    from types import SimpleNamespace
    from unittest.mock import Mock, patch

    from app.geo.content import geo_scheduler

    scheduler = SimpleNamespace(
        running=False,
        add_job=Mock(),
        start=Mock(),
        get_jobs=Mock(return_value=[]),
    )
    with (
        patch.object(geo_scheduler, "scheduler", scheduler),
        patch.object(geo_scheduler, "_acquire_lock", return_value=True),
    ):
        assert geo_scheduler.start_geo_scheduler()
    ids = [call.kwargs["id"] for call in scheduler.add_job.call_args_list]
    assert ids == [
        "geo_visibility_patrols",
        "geo_daily_metrics_nightly",
    ]


def test_independent_geo_process_keeps_recovery_alive_without_scheduler_ownership():
    import asyncio
    from unittest.mock import AsyncMock, patch

    import pytest

    from app.geo_main import _supervise_stale_reconciliation

    with (
        patch(
            "asyncio.sleep",
            AsyncMock(side_effect=[None, None, asyncio.CancelledError]),
        ),
        patch(
            "app.geo.content.geo_scheduler.run_geo_stale_reconciliation",
            AsyncMock(side_effect=[RuntimeError("temporary db error"), None]),
        ) as reconcile,
    ):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(_supervise_stale_reconciliation())
    assert reconcile.await_count == 2
