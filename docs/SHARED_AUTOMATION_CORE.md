# SEO/GEO automation shared core — development candidate

This package is a reusable control/storage library, not a deployed API or a
connected worker. It does not import SEO, GEO, SEM models or call a provider.
Schema and ACL scripts are review candidates; no Alembic revision is registered.
Production migration, deployment and provider/budget changes need separate approval.

## Files and entry points

- `app/automation_project_contract.py`: Configure, Control, Configuration; explicit
  task IDs, named owner, cycle and dispatch limit; rejects ambiguous numeric/bool input.
- `app/automation_projects.py`: shared transactions, state machine and read projections.
- `scripts/automation_projects_schema.sql`: projects, runs, idempotent commands,
  append-only events and four audit protection triggers.
- `scripts/automation_projects_permissions.sql`: reviewed existing runtime role
  and schema; grants only required privileges, no role creation.
- `tests/test_automation_projects_postgres.py`: independent native PostgreSQL
  suite with no SEO/GEO fixture imports. Every test uses and drops its own random schema.

`scope(module, tenant_id, scope_id)` uses SEO site ID or GEO project ID.
`schema_ready`/`require_schema` verify required columns, enabled correctly attached
audit triggers, table privileges and sequence usage. They are readiness checks,
not substitutes for a DBA reviewing constraints, function bodies, ownership and ACL.

`configure_project(db,key,Configure,actor_id)` and
`control_project(db,key,Control,actor_id)` return `(project,replayed,applied_version)`.
Replay returns the current project and the version originally applied. Same UUID
with different actor/content fails. The adapter must reauthorize even a replay.
Version changes include stop settlement; never assume exactly +1 per HTTP request.

`read_project`, `project_view`, `read_run`, `run_view`, `events_page`,
`project_events_page` and `runs_page`
are pure reads. Absent configuration is off. Adapters map missing/partial schema
to a read-only `schema_pending` project and unavailable writes to sanitized 503.
Add safe tenant_name/scope_name in the module adapter if available.
The exact capability enum is `capabilities.schema_state = "ready" | "pending"`.
`Project.state = "schema_pending"` is the project state when structure is pending;
these are different fields. Pending always disables writes and allowed actions.

## Required adapter responsibilities

Every public route and worker validates current named identity, assignment,
module entitlement, scope ownership, task eligibility and current financial guards.
This shared library cannot infer those from a module-neutral scope ID. Do not
expose it directly without those checks. Reject caller-selected evidence/URLs.
All transactions are owned by the caller: commit only on success, roll back on
every exception, including validation/event failures. No helper commits internally.
Use consistent lock order: project, run, then module site/task rows.

1. Explicit human Configure saves scope, cycle, limit and owner; no work starts.
2. Human control `start` creates one run with deterministic step request IDs.
   Scheduler `start_run` also locks/rejects stale or active snapshots, but scheduler
   callers must first verify due time, enabled cycle, live owner and scope.
3. `claim_step` reserves at most one running step per run, persists its event and
   increases the admission count. Commit before handing the token to a queue.
   Persist that exact token atomically with the child request. Module adapters
   reconcile orphan intents; they must never assume a restart means safe retry.
4. Immediately before outbound work, recheck live rights/limits and call
   `begin_dispatch(db,token)` under lock. Commit its event/marker before HTTP.
   Only a True result grants admission. False means previously admitted: do not
   call again. A crash after commit is uncertain and cannot automatically replay.
   This is not a substitute for a module queue's own single execution claim.
5. A pause linearizes at the project lock. Already admitted HTTP may still run;
   no database transaction can recall it. UI shows pausing/taking_over/ending
   while its result remains unresolved, never promises a refund or cancellation.
6. Before applying a business result, call `check_step` again in the same
   transaction as the module write. It fences changed generation/run/owner/task.
   If stale, omit the business write, retain real metering and call `settle_step`
   in a clean transaction. `settle_step` records stale success, clears result links,
   preserves fee evidence and finishes the stop when nothing remains in flight.
7. Resume only proceeds with pending steps; terminal/unknown/admitted steps never
   reset. Human end cancels pending steps, retains history and never creates
   acceptance evidence. Future cycle is independent; disable_cycle does not
   invalidate current work. Module adapters must not draft already completed tasks.

The running step includes an internal `dispatched_at` marker. It is a durable
admission timestamp, not evidence that a provider executed/charged successfully.
`fee_state` must be reconciled with actual module metering; uncertainty stays visible.
Without module adapters the library alone makes no claim of effective pause across
ranking, collection, publication, website mutation, approval or acceptance.

## History contract

GET `/api/v1/{module}/workbench/automation-projects/{scope_id}/runs`
with explicit `tenant_id`, optional `before_run_id` UUID, and limit 1–50 (default20):

```json
{"schema":1,"module":"seo","tenant_id":4,"scope_id":2,
 "items":[{"id":"12345678-1234-4234-8234-123456789abc","state":"ended",
 "started_at":"2026-10-11T00:00:00+00:00","finished_at":"2026-10-11T00:01:00+00:00"}],
 "next_before_run_id":null}
```

Stable descending `(created_at,id)` order; cursor must belong to the same module,
tenant and scope or 404. No global cursor lookup. `current_run_id` stays available
after end and reconfigure, then points to the next run after start. Historical run
and event reads remain available; no read starts/resumes work. Event pages use
ascending ID, limit 1–100, and `next_after_id`; no invented totals.

GET `/api/v1/{module}/workbench/automation-projects/{scope_id}/events`
with explicit tenant_id, after_id >= 0 (default0), limit 1–100 (default50) uses
`project_events_page(db,key,after_id=0,limit=50)` and returns
`{schema,module,tenant_id,scope_id,items,next_after_id}`. Each event retains its real
`run_id`, which may be null for initial configuration or cycle disable before a
first run. It includes all scope events across runs; the existing exact-run events
endpoint remains unchanged. An authorized but unconfigured scope returns an empty
page without creating a project. Never create synthetic runs for configuration.
Only scoped rows are queried; no global cursor/event lookup or read side effects.
All event codes are sanitized identifiers, never provider text or document bodies.

## Verification environment and limits

Run with `SEO_WORKFLOW_TEST_DATABASE_URL` (asyncpg, loopback host, database
`seo_workflow_test`, no URL query options) and
`SEO_WORKFLOW_TEST_ALLOW_SCHEMA_CREATE=yes`. No production/application DSN fallback.
`python -m pytest -q tests/test_automation_projects_postgres.py`

Coverage includes SEO/GEO scopes, concurrent start/claim/dispatch, idempotency,
restart uncertainty, pause/takeover/end fences and fee evidence, no automatic
acceptance, limits, independent cycle disable, stable scoped history, immutable
audit rows, partial schema/trigger/ACL refusal and log-failure rollback.
ACL script is exercised against the isolated schema-owning test role with grants
revoked as specified. No new login role is created; production role membership,
ownership and inherited privileges remain for the separate DBA review.
