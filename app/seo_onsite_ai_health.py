"""Read-only queue aggregation and process-local executor evidence.

No shared heartbeat is claimed: requests served by another process remain
unverified. Nothing in this module starts, repairs or replays a job.
"""
from datetime import datetime, timezone
from time import monotonic

from sqlalchemy import text

from app.config import get_settings
from app.seo_demo_runtime import seo_scheduler_may_start

STALE_SECONDS = 120
_owner = False
_stopped = False
_tick_monotonic = None
_tick = {"last_tick_at": None, "last_attempted": 0, "last_completed": 0, "last_error_code": None}


def worker_started():
    global _owner, _stopped, _tick_monotonic, _tick
    _owner, _stopped, _tick_monotonic = True, False, None
    _tick = {"last_tick_at": None, "last_attempted": 0, "last_completed": 0, "last_error_code": None}


def worker_stopped():
    global _owner, _stopped
    # Losing the election on a non-owner process is not an observed stop.
    _stopped = _stopped or _owner
    _owner = False


def record_tick(attempted, completed, *, failed=False):
    global _tick_monotonic, _tick
    if not _owner:
        return
    _tick_monotonic = monotonic()
    _tick = {"last_tick_at": datetime.now(timezone.utc).isoformat(),
             "last_attempted": attempted, "last_completed": completed,
             "last_error_code": "worker_batch_failed" if failed else None}


def worker_status():
    settings = get_settings()
    enabled = bool(seo_scheduler_may_start(settings) and settings.seo_external_actions_enabled)
    value = {"scope": "this_process", "enabled": enabled, "state": "unverified",
             "verified": False, "evidence": None, **_tick}
    if _tick_monotonic is not None:
        value["evidence"] = {"kind": "local_tick", "scope": "this_process"}
    if not enabled:
        value.update(state="stopped")
    elif _stopped:
        value.update(state="stopped")
    elif _owner and _tick_monotonic is not None and 0 <= monotonic() - _tick_monotonic <= STALE_SECONDS:
        value.update(state="degraded" if _tick["last_error_code"] else "active", verified=True)
    return value


QUEUE_QUERY = text("""
SELECT count(*) FILTER (WHERE run->>'state' = 'queued') AS queued,
       count(*) FILTER (WHERE run->>'state' = 'running') AS running,
       count(*) FILTER (WHERE run->>'state' = 'unknown') AS unknown,
       min((run->>'queued_at')::timestamptz)
           FILTER (WHERE run->>'state' = 'queued') AS oldest_queued_at,
       min((run->>'started_at')::timestamptz)
           FILTER (WHERE run->>'state' = 'running') AS oldest_running_at
FROM seo_tasks AS task
CROSS JOIN LATERAL jsonb_each(COALESCE(NULLIF(task.params->'onsite_ai_requests', 'null'::jsonb), '{}')) AS requests(key, run)
WHERE task.module = 'seo' AND task.action_type = 'onsite_optimization'
  AND task.params->'onsite'->>'schema' = '1'
""")


async def queue_status(session):
    # Only aggregate columns leave the database; no customer JSON is loaded.
    with session.no_autoflush:
        value = dict((await session.execute(QUEUE_QUERY)).mappings().one())
    for key in ("oldest_queued_at", "oldest_running_at"):
        if value[key] is not None:
            value[key] = value[key].astimezone(timezone.utc).isoformat()
    return {"state": "available", **value}


def unavailable_queue():
    return {"state": "schema_pending", "queued": None, "running": None, "unknown": None,
            "oldest_queued_at": None, "oldest_running_at": None}
