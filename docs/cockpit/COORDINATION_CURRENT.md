# Current coordination — 2026-09-07 15:43 Asia/Shanghai

This is the authoritative continuation checkpoint. Historical pause documents are superseded by the current user instruction to continue development and coordinate the existing SEM, SEO and GEO tasks.

## Operating instructions

- Keep the workbench and the three module tasks moving independently. Use exact-SHA review, cross-window review and green CI before merge. Use only controlled repository workflows for deployment.
- Preserve the product boundary: discovery/read evidence and explanation/action are separate. Never turn missing, stale, simulated, site-level or estimated data into customer facts.
- Database work and human tests require a concrete request to the user first: exact object, operation, expected result, prohibited actions and evidence to return. Work that does not need either must continue.
- Inspect the three tasks about every five minutes. Routine report about every fifteen minutes; material completion, failure or production risk is immediate.
- Stop line: if Codex primary remaining usage is below 20%, stop new development/tests/merge/deploy, pause all three tasks, update this file and notify the user. Do not consume a reset credit automatically. At 15:08 used was 66%, remaining 34%.

## Production state

- SEM backend: PR430 deployed as `3cadafae1cab7b8380f243c865305ca08d0dd386`, workflow `34093369715`, verify job `101651452893`, deploy job `101651564257`. Public `/health`=200, exact release and db=ok. Rollback `554934d6cbb2921f10f1fe165cbaf62f5b2544f8`.
- SEM frontend: PR427 deployed as `afcc63c270e9bcffe08d0295a416902ba6594a42`, workflow `34092436470`, deploy job `101648692353`. Coordinator independently rechecked `/health`=200 with backend `554934d6...`/db=ok and `/onboarding`=200 with the app shell. Rollback `ee3bf6c9077b99836a95f607abd44f2a9ac99264`.
- GEO: follow-up PR428 fixed the post-deploy review findings and deployed as `882802b44821db4bc1f8c9fc80cdf68931b80885`, workflow `34093141048`, migration=not-run. `/geo-health` and dashboard returned 200; db=ok. Rollback `eb1e05d40a73dc2b79ad25832a065462ba97b316`.
- SEO frontend: PR419 exact `a083b1687612883a5e488d4e8b0660ba84898149` passed independent review and five checks, merged as `e220900567fd191704bd6b44c5957cb10fb2d531`. Production SEO frontend workflow `34096271870` and baseline workflow `34096272471` succeeded. Post-release server/rollback evidence is being collected by the SEO owner.
- Formal workbench is now on main through PR432 merge `d1feded223af2b52815db07aac9126c040d0c5cd`. It is not yet in SEM frontend production.

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

- PR419 merged and its frontend production workflow succeeded as recorded above. It stores the ordinary login/session state atomically, keeps current-tab session priority, synchronizes persistent login changes between tabs and fails closed on old formats.
- Page-detail PR433 exact `ec85f51ce65b4cb49aecc5d73daf6d69c7fc1663` passed independent review, 191 backend plus 51 consumer/transport tests and all CI, then merged to main as `3f83bfb4dbf5f8bf3cc7fd1f8a7a922296b033bf`. It reads stored latest/previous crawl snapshot, link counts and at most 200 incoming sources after tenant+site+page proof. No crawl or write. Main checks passed; it is not yet deployed to the SEO backend production branch.

### Workbench

- PR429 frozen exact `d4f0d249e633657b7f042a7e2f84d742ab6c2085` passed SEO and SEM independent review with P1=0/P2=0 and all CI, then merged to main as `ca3c0fa08b6cdebd5cfa4fc922aa6472c3967f97`.
- Adds real SEO summary evidence for the explicitly selected site: content totals/statuses, review+ready counts, page totals/health/needs-fix, urgent count, and a clearly unavailable single-article-click card. It does not guess the first site, perform writes, trigger collection or infer article clicks.
- Adds module-only view invalidation so SEO permission/site failure clears SEO cards and discussion references without erasing valid SEM evidence. Site/customer/auth revision changes reject late results.
- Independent SEO review of the first head found one P2: business actions and unresolved modules were added together and described as modules. Exact `d4f0d24...` separates the two counts and adds four copy scenarios. Local validation now covers 50 SEO/workbench contracts plus cockpit scope, session, evidence-card and SEM UI suites; production build; `verify:sem-build` over 104 assets; diff check clean.
- The original gap was that a fresh ordinary SEO read-only user could not list/select sites because existing `/api/v1/seo/sites` requires `seo.assets`; the summary slice could only reuse an already selected scoped site.
- PR431 resolved that gap: exact `a42db9050ab45c7319d00e7d255fcb86a1d41cc2` exposed the tenant-qualified GET-only site list and merged as `b3db70ac648e4387047cf58bb29f883f520f393e`.
- Workbench PR432 added the customer-facing site selector and merged as `d1feded223af2b52815db07aac9126c040d0c5cd` from exact `26a266e33c9e8573c654a7a1c19e4a5bfa3aeb97`. Independent SEM review found and drove fixes for two P1 state transitions: invalidated sites cannot silently switch on the second reactive load, and the block remains isolated per tenant across A→B→A switching. Final review PASS P1=0/P2=0; 52 related contracts, frontend build and artifact verification passed.

## Ownership and next action

- Coordinator: keep exact-SHA/CI gates, independently inspect release diffs, maintain this file, and integrate the already reviewed GEO transport, authorization context and formal weekly metrics into the cockpit next. Do not turn the old prototype into production evidence.
- GEO: hotfix the three production review findings, obtain independent re-review, then controlled deploy; afterward interpret H1 result and define any next human test.
- SEO: finish PR419 production post-release evidence and prepare a controlled SEO backend release lane for the main-only site-scope/page-detail endpoints; do not publish customer content or wait on customer image feedback.
- SEM: continue bounded improvements that do not need human writeback; Smart Builder can remain deferred. No new real writeback test beyond the already authorized Open Tiger boundary.

## Human, database and administrator queue

- Human: the production `882802b...` retest generated V3/article #20 as an evidence-only fallback and preserved V1/V2, so the code mechanism passed. H1 remains blocked only because the task business profile uses `product_name=工业齿轮箱` while its facts/body use NORD/MAXXDRIVE. An authorized business user must change the profile's outward-facing brand/product name to `MAXXDRIVE`, place `NORD` in the brand description, then click only “重新检查” on existing V3. Do not regenerate, approve, create channel copy or publish. Return the resulting brand check, opening/conclusion checks, status, timestamp and screenshots. H2-H4 remain blocked until this passes.
- Database: no action now. No schema change is active.
- Administrator: no action now. Production workflows and health endpoints are available; request assistance only if a controlled workflow, credential retrieval or server evidence cannot be completed by the module owner.
