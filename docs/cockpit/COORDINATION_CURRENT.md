# Current coordination — 2026-09-07 14:56 Asia/Shanghai

This is the authoritative continuation checkpoint. Historical pause documents are superseded by the current user instruction to continue development and coordinate the existing SEM, SEO and GEO tasks.

## Operating instructions

- Keep the workbench and the three module tasks moving independently. Use exact-SHA review, cross-window review and green CI before merge. Use only controlled repository workflows for deployment.
- Preserve the product boundary: discovery/read evidence and explanation/action are separate. Never turn missing, stale, simulated, site-level or estimated data into customer facts.
- Database work and human tests require a concrete request to the user first: exact object, operation, expected result, prohibited actions and evidence to return. Work that does not need either must continue.
- Inspect the three tasks about every five minutes. Routine report about every fifteen minutes; material completion, failure or production risk is immediate.
- Stop line: if Codex primary remaining usage is below 20%, stop new development/tests/merge/deploy, pause all three tasks, update this file and notify the user. Do not consume a reset credit automatically. At 14:42 used was 62%, remaining 38%.

## Production state

- SEM backend: `554934d6cbb2921f10f1fe165cbaf62f5b2544f8`, workflow `34085269523`, public health exact release and db=ok. Rollback `22fcb30`.
- SEM frontend: PR427 deployed as `afcc63c270e9bcffe08d0295a416902ba6594a42`, workflow `34092436470`, deploy job `101648692353`. Coordinator independently rechecked `/health`=200 with backend `554934d6...`/db=ok and `/onboarding`=200 with the app shell. Rollback `ee3bf6c9077b99836a95f607abd44f2a9ac99264`.
- GEO: PR425 merged to production as `eb1e05d40a73dc2b79ad25832a065462ba97b316`; workflow `34091281245`, verify job `101645084484`, deploy job `101645313364`, baseline workflow `34091281266`, migration=not-run. `/geo-health` and dashboard returned 200 after deploy. Release directories report `20260907T063356Z-eb1e05d40a73`. This production revision is NOT accepted: independent post-deploy review found three P1/P2 paths below.
- Formal workbench PR426 merged to main as `086e73da78528e5910172190ef813b48460834a4` from exact business head `5b09683ae6164c11cb198c0fcce3c5cc94c8bd32`. It is not yet in SEM frontend production.

No migration was run. Coordinator/module tasks did not operate GEO task14, approve content, publish content or perform new real-customer writes.

## Active release and repair lanes

### GEO production hotfix — highest priority

Independent review of production merge `eb1e05d...` is BLOCKED:

1. `app/geo/content/gate.py` recomputes current Markdown brand state but a stale stored `task.rule_result.brand_validation=false` can still block corrected current content. Current recomputation must be authoritative; old metadata may be display/audit evidence only.
2. Manual publication validates before `_write_publication`, but the final locked write does not fresh-read current article and brand state and rerun the hard gate. A concurrent brand configuration change can pass the earlier check and still create a publication record.
3. Variant generation reads brand state before async model work and saves/marks ready from that old state. A concurrent brand change during generation can leave stale-ready variant metadata.

SEO independently reproduced the first path and reviewed the other two. Positive findings: score-gate disabled does not disable the brand hard gate; automatic connector delivery does fresh-read after reservation; the editor displays brand issue/recheck state. Coordinator sent all three fixes to GEO. GEO must front-fix, add both-direction stale-meta tests plus authorized PostgreSQL concurrency coverage, freeze an exact SHA, obtain independent review, then deploy with migration=not-run and verify health/assets/logs. Do not operate task14. H1 retest result has been forwarded to GEO; no new human retest is requested until this hotfix passes.

### SEM production sync

- Main PR420 merged as `e79795a03cf3cdc4b49d6497ed20f5b70d8d3038` from exact `973afb94e1ece797faac503a9fa9a050aa48ae0b`; main CI `34091358903` succeeded.
- PR427 exact `8df187a780da0978feb31ac070913bb18de6d97a` passed independent review and CI, merged and deployed as recorded above. It selected the SEM fixes and reviewed auth/session prerequisites, excluding backend, SEO main/router and database work.
- Post-release audit found the deployed backend search-term list still lacks account filtering. Draft PR430 exact `a66fa9dfb0019492e4e39587345c368d6507372c`, base/rollback `554934d6cbb2921f10f1fe165cbaf62f5b2544f8`, changes only `app/api/search_terms.py` and two tests. Reported 57 tests pass; all current GitHub checks are green and mergeability is clean. It awaits independent review and remains unmerged/unreleased.

### SEO

- Draft PR419 exact `a083b1687612883a5e488d4e8b0660ba84898149`, production SEO base `cc9a2af148f8d80af80fd1cb75bd7be383a5b3f8`; five SEO checks are green. It remains unmerged pending GEO independent review.
- Page-detail slice originally `e61f1a8` called a missing GET route. SEO added a bounded read-only backend route and tests; new frozen candidate is `ec85f51ce65b4cb49aecc5d73daf6d69c7fc1663`. It reads stored latest/previous crawl snapshot, link counts and at most 200 incoming sources after tenant+site+page proof. No crawl or write. Reported validation: 221 pytest and 43 consumer/transport tests. It awaits independent review and is not merged/deployed.
- SEO is queued to re-review the exact GEO hotfix and to review workbench PR429 after the production-risk lane.

### Workbench

- Draft PR429 exact `ede3942932e325f22d09a2ed7ac8f2159a4653ab`, branch `codex/workbench-seo-dashboard-20260907`, based on current main.
- Adds real SEO summary evidence for the explicitly selected site: content totals/statuses, review+ready counts, page totals/health/needs-fix, urgent count, and a clearly unavailable single-article-click card. It does not guess the first site, perform writes, trigger collection or infer article clicks.
- Adds module-only view invalidation so SEO permission/site failure clears SEO cards and discussion references without erasing valid SEM evidence. Site/customer/auth revision changes reject late results.
- Local validation: 48 SEO/workbench contract tests; cockpit scope, session, evidence-card and SEM UI suites; production build; `verify:sem-build` over 104 assets; diff check clean.
- PR429 is queued for SEO data-contract review and SEM session/invalidation review. Do not merge until both exact-head reviews and CI pass.
- PR429 GitHub checks are all green and mergeability is clean. Product gap still open: a fresh ordinary SEO read-only user cannot list/select sites because existing `/api/v1/seo/sites` requires `seo.assets`; current slice can only reuse an already selected scoped site. SEO owns a separate minimal GET-only site-scope endpoint/permission solution before this slice is considered production-complete.

## Ownership and next action

- Coordinator: keep exact-SHA/CI gates, independently inspect release diffs, maintain this file, and continue workbench slices. Do not turn the old prototype into production evidence.
- GEO: hotfix the three production review findings, obtain independent re-review, then controlled deploy; afterward interpret H1 result and define any next human test.
- SEO: review GEO hotfix first, then PR429; continue PR419 and `ec85f51...` without publishing or waiting on customer image feedback.
- SEM: finish PR430 independent review/release, then review PR429's SEM/session isolation. Smart Builder can remain deferred; no new real writeback test beyond the already authorized Open Tiger boundary.

## Human, database and administrator queue

- Human: no action now. The latest H1 result was handed to GEO, but current production needs the three-path hotfix first. Any next H1/H2-H4 request must name tenant/task, exact deployed version, one permitted operation, expected status/version, prohibited approval/publish actions, screenshots/network/log timestamp and cleanup.
- Database: no action now. No schema change is active.
- Administrator: no action now. Production workflows and health endpoints are available; request assistance only if a controlled workflow, credential retrieval or server evidence cannot be completed by the module owner.
