"""In-process telemetry for GEO schedulers.

The file lock decides which process executes scheduled work.  Telemetry is
therefore deliberately scoped to the process serving the request: a standby
process can report that another process owns the lock, but it cannot invent
the other process's run history.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED


def _iso(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class SchedulerTelemetry:
    """Keep a small, secret-free scheduler history for health/read APIs."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._lock = Lock()
        self._state = "stopped"
        self._owner = "none"
        self._state_changed_at = _iso()
        self._started_at: str | None = None
        self._jobs: dict[str, dict[str, Any]] = {}
        self._recent_failure: dict[str, Any] | None = None
        self._listener_targets: set[int] = set()

    def set_state(self, state: str, owner: str) -> None:
        with self._lock:
            self._state = state
            self._owner = owner
            self._state_changed_at = _iso()
            if state == "active":
                self._started_at = self._started_at or self._state_changed_at
            elif state == "stopped":
                self._started_at = None

    def record_failure(self, job_id: str, error: BaseException | str) -> None:
        failure = {
            "job_id": job_id,
            "at": _iso(),
            # Avoid putting exception messages in a public health response: HTTP
            # clients and SDKs sometimes include credentials in those messages.
            "error_type": type(error).__name__ if isinstance(error, BaseException) else str(error),
        }
        with self._lock:
            job = self._jobs.setdefault(job_id, {})
            job["recent_failure"] = failure
            job["last_run"] = failure["at"]
            self._recent_failure = failure

    def _listener(self, event: Any) -> None:
        job_id = str(getattr(event, "job_id", "unknown"))
        at = _iso(getattr(event, "scheduled_run_time", None))
        with self._lock:
            job = self._jobs.setdefault(job_id, {})
            job["last_run"] = at
            if getattr(event, "code", None) == EVENT_JOB_EXECUTED:
                job["last_success"] = at
                job["run_status"] = "succeeded"
                return
            error_type = (
                type(event.exception).__name__
                if getattr(event, "exception", None) is not None
                else "MissedRun"
            )
            failure = {"job_id": job_id, "at": at, "error_type": error_type}
            job["recent_failure"] = failure
            job["run_status"] = "failed" if event.code == EVENT_JOB_ERROR else "missed"
            self._recent_failure = failure

    def attach(self, scheduler: Any) -> None:
        add_listener = getattr(scheduler, "add_listener", None)
        target = id(scheduler)
        if not callable(add_listener) or target in self._listener_targets:
            return
        add_listener(
            self._listener,
            EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED,
        )
        self._listener_targets.add(target)

    def snapshot(self, scheduler: Any) -> dict[str, Any]:
        scheduled: dict[str, str | None] = {}
        get_jobs = getattr(scheduler, "get_jobs", None)
        if callable(get_jobs):
            try:
                for job in get_jobs():
                    scheduled[str(job.id)] = (
                        _iso(job.next_run_time) if getattr(job, "next_run_time", None) else None
                    )
            except Exception:  # pragma: no cover - defensive health path
                scheduled = {}
        with self._lock:
            job_ids = sorted(set(self._jobs) | set(scheduled))
            jobs = []
            for job_id in job_ids:
                saved = dict(self._jobs.get(job_id) or {})
                jobs.append({
                    "job_id": job_id,
                    "run_status": saved.get("run_status", "scheduled" if job_id in scheduled else "not_scheduled"),
                    "last_run": saved.get("last_run"),
                    "last_success": saved.get("last_success"),
                    "next_run": scheduled.get(job_id),
                    "recent_failure": saved.get("recent_failure"),
                })
            next_runs = [value for value in scheduled.values() if value]
            last_runs = [item["last_run"] for item in jobs if item["last_run"]]
            return {
                "name": self.name,
                "state": self._state,
                "owner": self._owner,
                "owner_process_id": os.getpid() if self._owner == "current_process" else None,
                "observation_scope": "current_process",
                "state_changed_at": self._state_changed_at,
                "started_at": self._started_at,
                "last_run": max(last_runs) if last_runs else None,
                "next_run": min(next_runs) if next_runs else None,
                "recent_failure": dict(self._recent_failure) if self._recent_failure else None,
                "jobs": jobs,
            }
