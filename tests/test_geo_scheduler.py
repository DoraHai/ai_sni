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


def test_geo_scheduler_registers_background_reconciliation():
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
        "geo_stale_reconciliation",
        "geo_daily_metrics_nightly",
    ]
