# Shared automation v2 integration package (local candidate)

This commit is intended to cherry-pick on top of the shared e8157e1c core.
It contains no SEO/GEO adapter implementation and no deployment/migration action.
Apply `automation_projects_v2_schema.sql` only after separate schema/ACL review;
existing runtime table-level grants cover its two additional columns. Keep all
append-only triggers. Drain old prepared-statement pools after approved DDL.

Configuration remains a union: old Configuration serializes identically (UUID
replays tested across schema installation); ConfigurationV2 has contract_version2,
operations, typed targets, service_plan, source_bindings, cycle, LimitsV2,
stop_condition and owner_user_id. Target is operation/object_type/object_id plus
source_revision/source_hash and optional variant. SourceBinding is kind/object_id/
revision/sha256. The module MUST reject unsupported operations, unsafe/unowned
targets, stale source bindings and partial takeover registries at each boundary.
The shared parser does not grant provider or publishing authority.

`core.start_run` builds typed steps for v2; non-onsite task_id is null, target
identifies the real object. Onsite keeps the legacy step key and numeric task_id.
`core.claim_step` returns a token containing operation+target for v2;
`core.check_step` fences changed run/generation/owner/target. It does not replace
live module authorization or source/registry hash validation.

`v2.begin_call(db,token,call_key,kind='provider'|'http')` is a per-external-request
admission: commit True before sending, False means never resend. Call keys and
run external-call limits are durable. `core.begin_dispatch` delegates to a primary
provider call for v2, while preserving v1 behavior. Unknown calls are never replayed.
`v2.finish_call(...,state,fee_state,evidence_refs)` records a bounded receipt even
after stop. Late known receipts may resolve unknown fees, but never adopt business
results. Check current token and module source in the SAME transaction as business
write. Nonterminal calls must be reconciled by the module; do not label a whole
multi-call operation complete because a single call finished.

`core.control_project` supports end_project only when v2 schema is ready. It sets
ended_at, disables future cycles, clears due time and fences in-flight generations
atomically. In-flight remains ending until step settlement. end keeps its old
meaning. No automatic acceptance evidence. To reopen, human must save configuration
again then explicitly start. A v2 configuration cannot downgrade to v1 or remove
an adopted operation and thereby silently reactivate the legacy scheduler.

`v2.ownership` reads explicit v2 operation adoption and fails closed on partial
structure/ACL/DB errors. `v2.check_legacy(db,key,operation)` additionally takes the
same scope advisory lock as configuration, covering the no-project-row race.
Call it before ANY business locks, both before external I/O and before result writes;
commit before the network. It rejects managed operations even when ended/paused.
Do not call it from a managed worker already holding project locks; use check_step
and the managed token instead. GEO must independently prove unique prompt×engine
ownership within tenant-wide legacy patrols and preserve stopped-target ownership.

Safe event changes are generated from allowlisted configuration/control fields;
invalid values/bodies are rejected. `v2.events_export_page` is same-scope, maximum
500 rows with snapshot_upper_id and next_after_id. This is an event-ID upper bound,
not a cross-request MVCC snapshot. `v2.csv_export` escapes formula cells.

`v2.health_snapshot(db,module,worker=...)` returns the agreed global health schema1:
scope global/tenant null, as_of, state, contract_versions, counts, rows<=50,
truncated, queue, worker, overall and finite safe alerts. projects is configured
rows; runs is history; pending_human counts current waiting_input/waiting_human/
taken_over runs; unknown_cost counts distinct historically admitted provider steps
with unresolved fee state, not money. Aggregates are independent of truncated rows.
Queue is explicitly not_connected/null until an adapter implements real queue
aggregation. Overall remains unverified without fleet evidence. Missing schema
keeps ALL count keys null; adapters sanitize DB errors to 503 and never return zero.
The HTTP endpoint must require named global superadmin, tenant null, both account
and customer settings edit rights; API keys/advisors are not sufficient.

Native test files: test_automation_projects_postgres.py and
test_automation_project_v2_postgres.py. Dedicated loopback test DB only; no provider
or production access. Module adapters must still test their full queues, actual
outbound boundaries, legacy recovery gates, permissions, sources and receipts.

Success-event actor correction is an additive follow-up commit: v1 successful
onsite work remains `ai`; v2 derives `ai` only for durable onsite_ai/content_draft
operations by default, other operations use `system`. It never trusts operation
from the caller token. Adapters with other AI operations must explicitly pass
`success_actor_kind='ai'` to settle_step; only `ai`/`system` are accepted. Failed,
stale and interrupted reconciliation events always remain `system`. This classifies
the producer of the successful step, not business approval or effect attribution.
GEO must cherry-pick this follow-up after the original shared v2 commit and classify
its own operations at the adapter call site. There is no schema change.
