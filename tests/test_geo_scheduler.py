from app.geo.content.geo_scheduler import (
    run_geo_daily_metrics_nightly,
    run_geo_visibility_patrols,
    scheduler_status,
)


def test_geo_scheduler_exports():
    assert callable(run_geo_daily_metrics_nightly)
    assert callable(run_geo_visibility_patrols)
    assert scheduler_status() in ("stopped", "running", "skipped")
