# Controlled runtime and distribution contract freeze — 2026-10-12

Frozen runtime: `9a5afb03bae76a9489db357f615267abef3ed9aa`. Local candidate, not deployed. Evidence and hashes: `DISTRIBUTION_CONTROLLED_RUNTIME_EVIDENCE_20261012.json`.

## Dependency assembly and scope

`scripts/distribution_assembled_worker.py` composes the exact clean native SEO or GEO runtime with central queue/planning files through Python package paths. No native file is copied or edited, and central config/security/models are not overwritten. Use separate SEO and GEO workers, each with its own native root; the worker filters its configured module. Config, models, native auth and cryptography stay owned by that native runtime. Shared dependency source commits and SHA256 are recorded per file in the two controls reports. The ten audited dependencies are config, database, auth, crypto, metering, API controls, connection configuration, usage-review basis and their two schema files. A notable shared source commit is `b23239234f62d622a0c2096df9e6b8e54a630810` (complete review-ledger gate); exact per-file provenance is in evidence.

Frozen roots: SEO `139cc7f57650afb1e83930149b6fac33cb9f861a`, GEO `ba713f06da330362cd0539531e4edd3216a09d78`. Both remained clean. Native settings and API controls are reused, including encrypted module credentials, official-provider connection validation, budget/concurrency admission and independently committed fees. Every planning call refreshes its own module context and restores the caller afterward; inherited SEO/SEM settings cannot choose GEO credentials. SEM funds dry-run remains true. There is no new supplier or legacy unmetered fallback. The assembled entry requires both API_CONTROLS_ENABLED=true and API_METERING_ENABLED=true.

Runtime command from central root (after separately reviewed candidate schemas exist; never executed against production in this batch):

```powershell
$env:API_CONTROLS_ENABLED='true'
$env:API_METERING_ENABLED='true'
# DATABASE_URL must point to the intended prepared candidate database.
& 'D:/SNIPERS国内版/ai_sni/.venv/Scripts/python.exe' scripts/distribution_assembled_worker.py --module seo --native-root ../seo-distribution-sources-20261011 --once --manifest "$env:TEMP/distribution-assembled-seo.json"
# GEO uses --module geo --native-root ../geo-distribution-source-20261011.
```

This command is an explicit worker entry, not a website/server deployment. The API stays the central distribution router attached by the native application/harness, preserving native JWT and authorization. The two native harnesses demonstrate this attachment and never start native scheduling, SEM operations or actual publication.

## Bounded fairness and attempt fencing

Per round: at most fifty scope inspections, twenty channel configs per scope, ten eligible entries per request and two model calls. Persisted scope check times prevent empty/revoked projects from starving later projects; binding cursors rotate configurations; already-planned entries are excluded before the ten-row limit. Regressions cover fifteen entries, sixty-five empty/denied scopes and twenty-six channels over recreated rounds.

A scope has a durable in-flight/unknown gate independent of the batch fingerprint. Adding a new draft cannot repeat an older running/unknown attempt. Recovery independently examines at most fifty stale running claims per round and changes them to unknown after sixty seconds. Recovered attempts cannot be revived by a late model response. Outer deadline cancellation, transport failures, HTTP error responses and attempted metering failures cannot silently become free retryable requests. Unknown project attempts stay held for investigation; pause/resume does not release this protection. Known invalid output remains bounded to three attempts with a five-minute delay.

Actual existing main metering tests cover admission followed by cancellation and cancellation after provider response during settlement: the former retains an unknown ledger event; the latter retains the durable requested event. Planner tests separately prove these timeout/unknown states never auto repeat. No automatic charge reversal or grant release is implemented.

## Validation and reproduction

All provider transports are synthetic. Real isolated PostgreSQL, existing main controls/metering/configuration and native SEO/GEO gates are used. Both controls-enabled suites verify admitted/attributed calls, money holds and usage cost, wrong inherited context, provider disabled, connection disabled/missing effective key, exhausted budget, invalid JSON, HTTP error, timeout, unknown concurrency hold, post-HTTP settlement failure and cancellation. These are thirteen named assertion groups per module, not twenty-six pytest tests.

SEO native/JWT flow has thirteen named checks including review, confirmation, channels, polling, pause/resume, version supersession, actual enabled-control gateway call and revocation. GEO has ten named checks including native review, permitted advisor, pause/resume, edited version invalidation and actual provider-call pause/revocation; four metered synthetic attempts leave zero publication tasks/reservations/native publications.

```powershell
# Dedicated owned databases only; create/start them explicitly before tests.
$env:DISTRIBUTION_TEST_DATABASE_URL='postgresql+asyncpg://distribution_test@127.0.0.1:55443/distribution_control_test'
& 'D:/SNIPERS国内版/ai_sni/.venv/Scripts/python.exe' scripts/verify_distribution_planning_controls.py --module seo --native-root ../seo-distribution-sources-20261011 --report "$env:TEMP/distribution-planning-controls-seo.json" --dependency-path "$env:TEMP/seo-test-pydeps"
# Repeat controls command with --module geo and its frozen native root.
$env:SEO_WORKFLOW_TEST_DATABASE_URL='postgresql+asyncpg://distribution_test@127.0.0.1:55443/seo_workflow_test'
$env:SEO_WORKFLOW_TEST_ALLOW_SCHEMA_CREATE='yes'
& 'D:/SNIPERS国内版/ai_sni/.venv/Scripts/python.exe' scripts/verify_distribution_seo_intake.py --controls-enabled --seo-root ../seo-distribution-sources-20261011 --seo-head 139cc7f57650afb1e83930149b6fac33cb9f861a --report "$env:TEMP/distribution-planning-enabled-native-seo.json" --dependency-path "$env:TEMP/seo-test-pydeps"
$env:GEO_TEST_POSTGRES_URL='postgresql+asyncpg://geo_ci@127.0.0.1:55507/geo_ci'
& 'D:/SNIPERS国内版/ai_sni/.venv/Scripts/python.exe' scripts/verify_distribution_geo_planning.py --native-root ../geo-distribution-source-20261011 --report "$env:TEMP/distribution-enabled-native-geo.json" --dependency-path "$env:TEMP/seo-test-pydeps"
```

114 backend checks passed, including the 22 planning checks. 184 workbench contracts passed. Distribution suite 40 passed, including 37 overlapping contract checks and three headless Edge browser checks. These totals are not additive. Frozen clean build manifest points to the runtime commit. Test schemas were removed and both owned database instances were stopped; TEMP logs/reports remain for diagnosis.

Schema order for a new candidate: native business fixture/schema → main metering → main API controls → distribution control → scheduling → publication → queue → planning. For an existing second-batch planning candidate, only `distribution_planner_fairness_schema.sql` adds the new scan table; do not reapply the non-idempotent full planning DDL. Rollback: stop worker, return code to the prior commit, retain planning/request/fee/audit history; the unused additive scan table can remain. No runtime DDL, destructive rollback or production migration occurred.

## Distribution execution boundary and next central seam

Available today: native completed-draft intake and current review/version gates; durable queue and advisory plans; project/channel authorization; canonical-account locking, limits and actual publication reservations; legacy explicit per-draft preflight/handoff/publish task grant; strict v1 device exchange and receipts; unknown receipt intervention; reported link → public-content check → native publication writeback and monitor status. Existing endpoints are `/project-channel`, `/control`, `/queue`, `/plans`, `/source`, `/tasks`, `/device/exchange`, `/task-resolution`, `/publication-check`, `/publication-writeback` and `/publication-monitor` under `/api/distribution/v1`. GET is read-only. Advisor scope is native/JWT authorized; superadmin owns global/binding/policy settings; customers retain delivery views.

Missing from the automatic queue path: validated executable capability manifest from the independent device window, persistent queue/version/plan → execution-task association, project-level explicit consent for any verified handoff stage, and a bounded idempotent dispatcher choosing only an admitted stage. This batch intentionally does not mint those grants. Normal project polling/queueing/planning needs no repeated per-draft start button. Legacy manual publication authorization is still separate and cannot be inferred from selecting a queue channel.

Next integration must freeze device manifest/fixture version and approved human/synthetic steps, then bind queue_id + exact draft/source/digest + plan_id + binding + canonical account to one idempotent execution intent. It may admit verified preflight/human handoff stages; formal publish remains separately authorized. Dispatch must recheck native approval, authorization, capability, active binding and account constraints, and retain task association across retries/restarts. Receipts must remain strict v1; completion of handoff is not published evidence. CAPTCHA/login/unknown stays human intervention. Existing reservations/locks across projects/devices remain central authority. No real GUI, account, AI payment, publication, website, production DDL or deploy is authorized by this freeze.
