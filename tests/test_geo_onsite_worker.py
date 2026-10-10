"""No-network checks for the durable GEO onsite worker supervisor."""
import asyncio
from types import SimpleNamespace

import pytest

from app.geo import onsite_jobs, onsite_routes


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute(self, _statement):
        return [SimpleNamespace(id=7, tenant_id=3)]


def _session_factory():
    return _Session()


def test_pending_batch_surfaces_runner_exception_instead_of_reporting_normal_tick():
    async def runner(_job_id, _tenant_id):
        raise RuntimeError("secret provider detail must not reach health output")

    with pytest.raises(onsite_jobs.PendingBatchError) as error:
        asyncio.run(onsite_jobs.run_pending_batch(
            session_factory=_session_factory, runner=runner,
        ))
    assert "1 queued job runner(s) failed" in str(error.value)
    assert "RuntimeError" in str(error.value)
    assert "secret provider detail" not in str(error.value)


def test_supervisor_keeps_failed_tick_degraded_until_success_and_stops_on_cancel(monkeypatch):
    entered_sleep = asyncio.Event()

    async def failed_batch():
        raise onsite_jobs.PendingBatchError("sanitized")

    async def wait_for_cancel(_seconds):
        entered_sleep.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(onsite_jobs, "run_pending_batch", failed_batch)
    monkeypatch.setattr(onsite_jobs.asyncio, "sleep", wait_for_cancel)
    monkeypatch.setattr("app.config.get_settings", lambda: SimpleNamespace(
        geo_async_worker_enabled=True,
    ))
    onsite_jobs._worker_status.update(
        enabled=False, state="stopped", last_tick_at=None,
        last_attempted=0, last_completed=0, last_error=None,
    )

    async def check():
        worker = asyncio.create_task(onsite_jobs.supervise_pending_jobs())
        await asyncio.wait_for(entered_sleep.wait(), 1)
        health = onsite_jobs.pending_worker_status()
        assert health["state"] == "degraded"
        assert health["last_error"] == "PendingBatchError"
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker
        assert onsite_jobs.pending_worker_status()["state"] == "stopped"

    asyncio.run(check())


def test_public_request_run_allows_only_fixed_diagnostics_and_states():
    job = SimpleNamespace(
        id=9, ref_id=14, status="failed", created_at=None, started_at=None,
        finished_at=None, request_meta={"request_id": "request-1"},
        result_meta={
            "public_state": "secret-upstream-state", "message": "safe public message",
            "error_category": "secret-upstream-category",
            "error_code": "sk-secret-shaped-provider-code", "http_status": True,
        },
    )
    unsafe = onsite_routes._request_run(job)
    assert unsafe["state"] == "failed"
    assert unsafe["error_category"] is None
    assert unsafe["error_code"] is None
    assert unsafe["http_status"] is None
    assert "secret-shaped" not in str(unsafe)

    job.result_meta = {
        "public_state": "failed", "message": "safe public message",
        "error_category": "admission_denied",
        "error_code": "api_concurrency_limit", "http_status": 429,
    }
    safe = onsite_routes._request_run(job)
    assert safe["state"] == "failed"
    assert safe["error_category"] == "admission_denied"
    assert safe["error_code"] == "api_concurrency_limit"
    assert safe["http_status"] == 429
