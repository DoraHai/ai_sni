# Current coordination — 2026-09-07 16:52 Asia/Shanghai

This is the authoritative continuation checkpoint. Historical pause documents are superseded by the current user instruction to continue development and coordinate the existing SEM, SEO and GEO tasks.

## Latest production checkpoint — supersedes older state below

- Workbench production frontend PR437 was independently re-reviewed at exact head `de80c703b3006c264dc553b81ae15303724a11cc`: PASS, P1=0/P2=0. Required `pytest` and `sem-frontend-build` checks passed. It merged into `codex/production-sem` as `01a49b27ee352e05c2a5466c93b75571701e06a9`.
- Production workflow `34102095820` completed successfully: `pytest`, `sem-frontend-build` and `Deploy SEM frontend only` all succeeded. Active release is `/opt/sem-frontend/releases/20260907T084412Z-01a49b27ee35`; previous/rollback release is `/opt/sem-frontend/releases/20260907T064845Z-afcc63c270e9`.
- Coordinator and SEM-owner public no-auth smoke passed for `/workspace`, `/workspace/cockpit`, `/monitor/dashboard`, `/optimize/keywords`, `/optimize/search-terms`, `/login`, favicon, the index assets and the lazy workbench chunks. HTML is no-store/no-cache and hashed assets are immutable. `AcquisitionCockpitView-Sjbh7YYi.js` and `ModuleWorkspaceView-DUYsG2N-.js` both return 200, contain `/seo/site`, and do not contain stale `/seo/sites`. Public `/DEPLOYED_GIT_COMMIT` is intentionally not exposed and returns 404; exact deployment identity is evidenced by the controlled workflow's release marker check, active release path and matching public chunks.
- SEO backend PR436 exact `22ff3f6bc67693d069e76e94dd22d0e4b7e475d3` passed independent review and all five checks, then merged into `codex/production-seo` as `e0d04cf37f6deb6241038fc0c41b579acaacd1fa`. Production deployment workflow `34100854396` and baseline `34100855025` succeeded, migration=`not-run`, public `/seo-health`=200 with `env=prod`, db/schema ok. Active backend/frontend releases are `/opt/seo-service/releases/20260907T083042Z-e0d04cf37f6d` and `/opt/seo-frontend/releases/20260907T083042Z-e0d04cf37f6d`; rollback backend is `20260906T064845Z-5ef5bab99b5c` and rollback frontend is `20260907T073656Z-e220900567fd-frontend`.
- The production workbench now carries real read-only SEM, SEO and GEO integrations. It is no longer the fake-data prototype. Authenticated tenant/module/menu/data acceptance remains separate from the public shell smoke and must not be claimed until performed with an authorized test identity.
- GEO H1 human retest results have been delivered to the GEO owner. GEO must interpret them and continue H2-H4 automation/static work without operating task #14 or waiting for another human action.
- The user removed the temporary usage stop line. Continue development, review, merge and controlled deployment without pausing at 20% remaining. Database changes, real-customer writes and human-only acceptance still require a concrete request and explicit coordination.

## Operating instructions

- Keep the workbench and the three module tasks moving independently. Use exact-SHA review, cross-window review and green CI before merge. Use only controlled repository workflows for deployment.
- Module-owner boundary is strict. SEM owns SEM code, SEO owns SEO code, and GEO owns GEO code. Each owner develops and tests only its assigned module and reports directly to the coordinator. An owner must not edit another module, declare another module complete, coordinate database/admin/human work, or widen a production release without an explicit coordinator assignment.
- The coordinator owns cross-module contracts, workbench integration, task assignment, review assignment, merge order, deployment coordination, human/database/admin requests and the authoritative continuation record. A module owner reports a cross-module finding as evidence and a proposed contract; the coordinator decides where the fix belongs.
- Cross-review is allowed only when explicitly assigned by the coordinator. A reviewer reports P1/P2 findings against an exact SHA and does not take ownership of the reviewed module or make unrequested edits.
- Every module handoff must name: objective and boundary, branch/PR, exact head/base/merge SHA, files changed, tests and CI, review result, deployment/current/rollback state, unresolved items, dependencies, and any requested human/database/admin action. Separate verified facts from assumptions and pending checks.
- Preserve the product boundary: discovery/read evidence and explanation/action are separate. Never turn missing, stale, simulated, site-level or estimated data into customer facts.
- Database work and human tests require a concrete request to the user first: exact object, operation, expected result, prohibited actions and evidence to return. Work that does not need either must continue.
- Inspect the three tasks about every five minutes. Routine report about every fifteen minutes; material completion, failure or production risk is immediate.
- There is currently no usage-based stop line. Continue the authorized work; do not consume a reset credit unless the user explicitly asks.

## Production state

- SEM backend: PR430 deployed as `3cadafae1cab7b8380f243c865305ca08d0dd386`, workflow `34093369715`, verify job `101651452893`, deploy job `101651564257`. Public `/health`=200, exact release and db=ok. Rollback `554934d6cbb2921f10f1fe165cbaf62f5b2544f8`.
- SEM frontend: PR427 deployed as `afcc63c270e9bcffe08d0295a416902ba6594a42`, workflow `34092436470`, deploy job `101648692353`. Coordinator independently rechecked `/health`=200 with backend `554934d6...`/db=ok and `/onboarding`=200 with the app shell. Rollback `ee3bf6c9077b99836a95f607abd44f2a9ac99264`.
- GEO: current production is PR434 merge `f694ddbdeba8026271860089a3d16cfd534b8627`, deployment workflow `34097293229` and baseline `34097293203` succeeded, migration=not-run. `/geo-health`=200, db=ok, both schedulers running and dashboard=200. It retains the PR428 final gate fixes and adds current-brand recheck for the existing V3 without regeneration.
- SEO frontend: PR419 exact `a083b1687612883a5e488d4e8b0660ba84898149` passed independent review and five checks, merged as `e220900567fd191704bd6b44c5957cb10fb2d531`. Production SEO frontend workflow `34096271870` and baseline workflow `34096272471` succeeded. Post-release server/rollback evidence is being collected by the SEO owner.
- Formal workbench is now on main through GEO summary PR435 merge `d93acd8bde4cd1cfdb73c980dd1d75d99f32f5a0`. It is not yet in SEM frontend production.

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
- Workbench PR435 merged as `d93acd8bde4cd1cfdb73c980dd1d75d99f32f5a0` from exact `72111a00e4ebf01144a01498ae18f065c6a13504`. It mounts the reviewed GEO GET-only transport and GEO-owned authorization context, then shows six complete-week cards: AI mentions, mention rate, visibility score, qualified answers, valid questions and covered engines. Simulated/manual/unknown/excluded/insufficient data remain unavailable and answer rows are not re-aggregated. Independent SEM review PASS P1=0/P2=0; all PR CI passed.

## Ownership and next action

- Coordinator: keep exact-SHA/CI gates, independently inspect release diffs, maintain this file, and integrate the already reviewed GEO transport, authorization context and formal weekly metrics into the cockpit next. Do not turn the old prototype into production evidence.
- GEO: hotfix the three production review findings, obtain independent re-review, then controlled deploy; afterward interpret H1 result and define any next human test.
- SEO: finish PR419 production post-release evidence and prepare a controlled SEO backend release lane for the main-only site-scope/page-detail endpoints; do not publish customer content or wait on customer image feedback.
- SEM: continue bounded improvements that do not need human writeback; Smart Builder can remain deferred. No new real writeback test beyond the already authorized Open Tiger boundary.

## Human, database and administrator queue

- Human: on production `f694ddb...`, an authorized tester must open tenant 诺德 → GEO task #14 → existing V3/article #20 and click exactly once “按当前品牌重新检查”. Do not edit/regenerate the draft, approve, create channel copy or publish. Return the full brand check, opening/conclusion checks, V3 status, timestamp, screenshots and any console/network error. This is H1 acceptance only; H2-H4 remain separate.
- Database: no action now. No schema change is active.
- Administrator: no action now. Production workflows and health endpoints are available; request assistance only if a controlled workflow, credential retrieval or server evidence cannot be completed by the module owner.
