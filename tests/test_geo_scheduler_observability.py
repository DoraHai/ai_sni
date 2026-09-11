from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from apscheduler.events import EVENT_JOB_EXECUTED

from app.geo.scheduler_observability import SchedulerTelemetry


def test_scheduler_telemetry_explains_owner_runs_and_failure_without_message():
    telemetry = SchedulerTelemetry("test")
    next_run = datetime.now(timezone.utc) + timedelta(minutes=5)
    scheduler = NS(get_jobs=lambda: [NS(id="job-a", next_run_time=next_run)])
    telemetry.set_state("active", "current_process")
    telemetry.record_failure("job-a", RuntimeError("token=must-not-leak"))

    result = telemetry.snapshot(scheduler)

    assert result["state"] == "active"
    assert result["owner"] == "current_process"
    assert result["owner_process_id"]
    assert result["next_run"].endswith("Z")
    assert result["last_run"].endswith("Z")
    assert result["recent_failure"]["error_type"] == "RuntimeError"
    assert "must-not-leak" not in str(result)


def test_callback_executed_event_does_not_hide_business_failure_from_same_run():
    telemetry = SchedulerTelemetry("test")
    scheduled_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    telemetry.record_failure("job-a", RuntimeError("one item failed"))

    telemetry._listener(NS(
        job_id="job-a",
        code=EVENT_JOB_EXECUTED,
        scheduled_run_time=scheduled_at,
        exception=None,
    ))
    item = telemetry.snapshot(NS(get_jobs=lambda: []))["jobs"][0]

    assert item["callback_status"] == "completed"
    assert item["run_status"] == "degraded"
    assert item["last_success"] is None
    assert item["recent_failure"]["error_type"] == "RuntimeError"


def test_later_clean_callback_can_become_successful_after_older_failure():
    telemetry = SchedulerTelemetry("test")
    telemetry.record_failure("job-a", RuntimeError("old item failure"))
    later_run = datetime.now(timezone.utc) + timedelta(minutes=1)

    telemetry._listener(NS(
        job_id="job-a",
        code=EVENT_JOB_EXECUTED,
        scheduled_run_time=later_run,
        exception=None,
    ))
    item = telemetry.snapshot(NS(get_jobs=lambda: []))["jobs"][0]

    assert item["callback_status"] == "completed"
    assert item["run_status"] == "succeeded"
    assert item["last_success"] is not None


def test_content_scheduler_reports_skipped_when_another_process_owns_lock():
    from app.geo.content import geo_scheduler

    scheduler = NS(running=False, get_jobs=Mock(return_value=[]))
    with (
        patch.object(geo_scheduler, "scheduler", scheduler),
        patch.object(geo_scheduler, "_acquire_lock", return_value=False),
    ):
        assert geo_scheduler.start_geo_scheduler() is False
        result = geo_scheduler.scheduler_runtime_status()

    assert result["state"] == "skipped"
    assert result["owner"] == "another_process"
    assert result["observation_scope"] == "current_process"


def test_followup_scheduler_reports_standby_when_another_process_owns_lock():
    from app.geo import scheduler as followup

    scheduler = NS(running=False, get_jobs=Mock(return_value=[]))
    with (
        patch.object(followup, "geo_scheduler", scheduler),
        patch.object(followup, "_acquire_scheduler_lock", return_value=False),
    ):
        assert followup.start_geo_followup_scheduler() is False
        result = followup.followup_scheduler_runtime_status()

    assert result["state"] == "standby"
    assert result["owner"] == "another_process"


def test_runtime_read_endpoint_exposes_both_schedulers_without_writes():
    import asyncio

    from app.geo.read_routes import get_runtime_status

    ctx = Mock()
    session = Mock(
        add=Mock(side_effect=AssertionError("write forbidden")),
        commit=Mock(side_effect=AssertionError("write forbidden")),
    )
    with (
        patch(
            "app.geo.content.geo_scheduler.scheduler_runtime_status",
            return_value={"state": "skipped", "owner": "another_process"},
        ),
        patch(
            "app.geo.scheduler.followup_scheduler_runtime_status",
            return_value={"state": "active", "owner": "current_process"},
        ),
    ):
        result = asyncio.run(get_runtime_status(1, ctx, session))

    ctx.ensure_tenant.assert_called_once_with(1)
    assert result["read_only"] is True
    assert result["schedulers"]["content"]["state"] == "skipped"
    assert result["schedulers"]["followup"]["state"] == "active"
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_geo_health_keeps_legacy_fields_and_adds_structured_runtime():
    import asyncio

    from app import geo_main

    class ConnectionContext:
        async def __aenter__(self):
            return NS(execute=AsyncMock())

        async def __aexit__(self, *_args):
            return None

    response = NS(status_code=200)
    engine = NS(connect=lambda: ConnectionContext())
    with (
        patch.object(geo_main, "engine", engine),
        patch.object(geo_main, "scheduler_status", return_value="skipped"),
        patch.object(geo_main, "scheduler_runtime_status", return_value={"state": "skipped"}),
        patch.object(
            geo_main,
            "followup_scheduler_runtime_status",
            return_value={"state": "standby"},
        ),
        patch.object(geo_main, "followup_scheduler", NS(running=False)),
    ):
        result = asyncio.run(geo_main.geo_health(response))

    assert response.status_code == 200
    assert result["geo_scheduler"] == "skipped"
    assert result["geo_followup_scheduler"] == "standby"
    assert result["scheduler_runtime"] == {
        "content": {"state": "skipped"},
        "followup": {"state": "standby"},
    }
