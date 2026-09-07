# Current coordination — 2026-09-07 14:56 Asia/Shanghai

This is the authoritative continuation checkpoint. Historical pause documents are superseded by the current user instruction to continue development and coordinate the existing SEM, SEO and GEO tasks.

## Operating instructions

- Keep the workbench and the three module tasks moving independently. Use exact-SHA review, cross-window review and green CI before merge. Use only controlled repository workflows for deployment.
- Preserve the product boundary: discovery/read evidence and explanation/action are separate. Never turn missing, stale, simulated, site-level or estimated data into customer facts.
- Database work and human tests require a concrete request to the user first: exact object, operation, expected result, prohibited actions and evidence to return. Work that does not need either must continue.
- Inspect the three tasks about every five minutes. Routine report about every fifteen minutes; material completion, failure or production risk is immediate.
- Stop line: if Codex primary remaining usage is below 20%, stop new development/tests/merge/deploy, pause all three tasks, update this file and notify the user. Do not consume a reset credit automatically. At 14:42 used was 62%, remaining 38%.

## Production state

- SEM backend: PR430 deployed as `3cadafae1cab7b8380f243c865305ca08d0dd386`, workflow `34093369715`, verify job `101651452893`, deploy job `101651564257`. Public `/health`=200, exact release and db=ok. Rollback `554934d6cbb2921f10f1fe165cbaf62f5b2544f8`.
- SEM frontend: PR427 deployed as `afcc63c270e9bcffe08d0295a416902ba6594a42`, workflow `34092436470`, deploy job `101648692353`. Coordinator independently rechecked `/health`=200 with backend `554934d6...`/db=ok and `/onboarding`=200 with the app shell. Rollback `ee3bf6c9077b99836a95f607abd44f2a9ac99264`.
- GEO: follow-up PR428 fixed the post-deploy review findings and deployed as `882802b44821db4bc1f8c9fc80cdf68931b80885`, workflow `34093141048`, migration=not-run. `/geo-health` and dashboard returned 200; db=ok. Rollback `eb1e05d40a73dc2b79ad25832a065462ba97b316`.
- Formal workbench PR426 merged to main as `086e73da78528e5910172190ef813b48460834a4` from exact business head `5b09683ae6164c11cb198c0fcce3c5cc94c8bd32`. It is not yet in SEM frontend production.

No migration was run. Coordinator/module tasks did not operate GEO task14, approve content, publish content or perform new real-customer writes.

## Active release and repair lanes

### GEO production hotfix — highest priority

Independent review of production merge `eb1e05d...` found and reproduced these blockers:

1. `app/geo/content/gate.py` recomputes current Markdown brand state but a stale stored `task.rule_result.brand_validation=false` can still block corrected current content. Current recomputation must be authoritative; old metadata may be display/audit evidence only.
2. Manual publication validates before `_write_publication`, but the final locked write does not fresh-read current article and brand state and rerun the hard gate. A concurrent brand configuration change can pass the earlier check and still create a publication record.
3. Variant generation reads brand state before async model work and saves/marks ready from that old state. A concurrent brand change during generation can leave stale-ready variant metadata.

GEO fixed all three on exact reviewed head `4da1183dcbd5b47e0b15cd945c7e0765ffefb6a9`, with current content/brand authoritative, final locked publication revalidation, and post-generation/pre-save variant revalidation. Independent review passed P1=0/P2=0. Evidence: `1029 passed, 43 skipped`, frontend build, PR CI and real PostgreSQL double-session concurrency checks. It merged/deployed as recorded above. Do not operate task14 from an agent. H1 now needs one human retest on this exact production release.

### SEM production sync

- Main PR420 merged as `e79795a03cf3cdc4b49d6497ed20f5b70d8d3038` from exact `973afb94e1ece797faac503a9fa9a050aa48ae0b`; main CI `34091358903` succeeded.
- PR427 exact `8df187a780da0978feb31ac070913bb18de6d97a` passed independent review and CI, merged and deployed as recorded above. It selected the SEM fixes and reviewed auth/session prerequisites, excluding backend, SEO main/router and database work.
- Post-release audit found the backend search-term list lacked account filtering. PR430 exact `a66fa9dfb0019492e4e39587345c368d6507372c` changed only `app/api/search_terms.py` and two tests, passed independent review, 57 tests and CI, then merged/deployed as recorded above. No migration, sync or business write ran.

### SEO

- Draft PR419 exact `a083b1687612883a5e488d4e8b0660ba84898149`, production SEO base `cc9a2af148f8d80af80fd1cb75bd7be383a5b3f8`; five SEO checks are green. It remains unmerged pending GEO independent review.
- Page-detail slice originally `e61f1a8` called a missing GET route. SEO added a bounded read-only backend route and tests; new frozen candidate is `ec85f51ce65b4cb49aecc5d73daf6d69c7fc1663`. It reads stored latest/previous crawl snapshot, link counts and at most 200 incoming sources after tenant+site+page proof. No crawl or write. Reported validation: 221 pytest and 43 consumer/transport tests. It awaits independent review and is not merged/deployed.
- SEO is queued to re-review the exact GEO hotfix and to review workbench PR429 after the production-risk lane.

### Workbench

- Draft PR429 current frozen exact `d4f0d249e633657b7f042a7e2f84d742ab6c2085`, branch `codex/workbench-seo-dashboard-20260907`, based on current main.
- Adds real SEO summary evidence for the explicitly selected site: content totals/statuses, review+ready counts, page totals/health/needs-fix, urgent count, and a clearly unavailable single-article-click card. It does not guess the first site, perform writes, trigger collection or infer article clicks.
- Adds module-only view invalidation so SEO permission/site failure clears SEO cards and discussion references without erasing valid SEM evidence. Site/customer/auth revision changes reject late results.
- Independent SEO review of the first head found one P2: business actions and unresolved modules were added together and described as modules. Exact `d4f0d24...` separates the two counts and adds four copy scenarios. Local validation now covers 50 SEO/workbench contracts plus cockpit scope, session, evidence-card and SEM UI suites; production build; `verify:sem-build` over 104 assets; diff check clean.
- PR429 is queued for SEO data-contract review and SEM session/invalidation review. Do not merge until both exact-head reviews and CI pass.
- PR429 GitHub checks are all green and mergeability is clean. Product gap still open: a fresh ordinary SEO read-only user cannot list/select sites because existing `/api/v1/seo/sites` requires `seo.assets`; current slice can only reuse an already selected scoped site. SEO owns a separate minimal GET-only site-scope endpoint/permission solution before this slice is considered production-complete.

## Ownership and next action

- Coordinator: keep exact-SHA/CI gates, independently inspect release diffs, maintain this file, and continue workbench slices. Do not turn the old prototype into production evidence.
- GEO: hotfix the three production review findings, obtain independent re-review, then controlled deploy; afterward interpret H1 result and define any next human test.
- SEO: review GEO hotfix first, then PR429; continue PR419 and `ec85f51...` without publishing or waiting on customer image feedback.
- SEM: finish PR430 independent review/release, then review PR429's SEM/session isolation. Smart Builder can remain deferred; no new real writeback test beyond the already authorized Open Tiger boundary.

## Human, database and administrator queue

- Human: H1 must now be rerun once against production `882802b...`: tenant 诺德, task #14, one hard refresh and one “更新母稿”; capture job/version/type, saved result or full brand warning, score/checks, network/console error and timestamp/screenshots. Do not approve, generate channel copy or publish. Return exact result to GEO/coordinator. H2-H4 remain blocked until H1 passes.
- Database: no action now. No schema change is active.
- Administrator: no action now. Production workflows and health endpoints are available; request assistance only if a controlled workflow, credential retrieval or server evidence cannot be completed by the module owner.
