# Current coordination — 2026-09-07 14:30 Asia/Shanghai

User resumed development. Historical pause documents do not represent current instructions.

## Current user instructions

- Continue the workbench and coordinate the three existing SEM, SEO and GEO tasks. Keep their work independent where possible and use cross-review before merge.
- Preserve context in this file with exact commits, test evidence, production evidence, scope boundaries and the next owner/action. Do not infer completion from an idle task.
- Ask the user with a concrete checklist before a database change or required human test. Work that does not depend on either continues.
- Check every five minutes and report routine progress every fifteen minutes; report material failures/completions immediately.
- Usage stop line: Codex primary remaining usage below 20%. At 14:25 the account tool reported used 61%, remaining 39%. Automation-2 checks usage first; below the line it must pause new development/tests/merge/deploy, pause the three module tasks, update this document and notify the user. It must not consume a reset credit automatically.

## Completed releases

- SEM backend PR421: deployed `554934d6cbb2921f10f1fe165cbaf62f5b2544f8`, run `34085269523`. Coordinator independently confirmed public health release_commit and db=ok. Rollback baseline `22fcb30`.
- SEM frontend PR422: deployed `ee3bf6c9077b99836a95f607abd44f2a9ac99264`, run `34084823098`; owner confirmed onboarding/assets and new ledger markers. Rollback baseline `b07e32d`.
- GEO PR423: deployed `8af28f3125cfd4059452d7f5c3067986442eb0a4`, run `34085373873`, verify job `101628285071`, deployment job `101628424440`, successful. Deployment log reports both release directories and migration=not-run. Public geo-health and dashboard 200; db=ok; index-DW6fitbf.js, GeoFactsView-jwuwovqS.js and GeoTaskEditorView-Hedjz-aK.js contain reviewed changes. Rollback baseline `c8883a3`; current server previous symlink not independently inspected.
- GEO independent PG evidence: verify-only `dcfa504`, run `34085251595`, exact 11 names, no skips/failures. Artifact digest `8b0f3c9fbeaaf4db70776f5fdd6a0371c2c34c4e205c7210418d3141127f014d`. Verify-only files were NOT merged. Business SHA was `dc68e9b`.

No migration, task14 generation, publication, or new real writeback test was performed in these releases. H1 human acceptance remains pending on the new release; old failed attempts are not accepted retroactively.

## Active work

- SEM PR420 draft exact `973afb94e1ece797faac503a9fa9a050aa48ae0b`: repairs multi-account defaults, disabled-account write prevention, dialog/request context races, auth-revision immediate clearing across five views, AccountBudget pending-load clearing, and KeywordWorkbench same-account active→disabled mode invalidation. Coordinator reran mounted auth/classic component tests, SEM UI contracts, build/verify and production audit successfully; all GitHub CI is green. SEO is performing the final cross-window review. Keep the head frozen and do not merge/deploy until that PASS.
- SEO PR419 exact `a083b1687612883a5e488d4e8b0660ba84898149`: ready locally, awaiting GEO independent review. Production remains separate from the candidate. SEO also owns selecting one high-priority offline gap from its 34-item mapping; no customer publishing or image feedback wait is required for that selection.
- GEO follow-up PR425 is still draft; current moving head is `0e3bb5f52ceaa245ab8f3ab210f3e9712ed7398f` onto production GEO `8af28f3`. After the initial brand-readiness fix, review found further delivery-time stale-state paths; GEO added variant/publish/delivery-time fresh brand checks and PostgreSQL delivery coverage. CI is still running on this newest SHA, and no independent final PASS exists yet. No merge/deploy/task14 action until the head stabilizes and passes.
- Workbench view-state PR424 merged to main as `b99479efab18bb9a4146fb03b46510ddd86bdb94`. Formal page PR426 exact `5b09683ae6164c11cb198c0fcce3c5cc94c8bd32` passed three independent review rounds and all CI, then merged to main as `086e73da78528e5910172190ef813b48460834a4`. It provides the protected full-screen acquisition cockpit shell, customer-level module qualification, real read-only SEM report evidence, expandable cards, action ledger and guided conversation; local HTTP preview performs zero identity/business reads. It has not yet been promoted to `codex/production-sem`; production promotion must include its reviewed session/transport/view-state prerequisites without pulling unrelated main frontend changes.
- Workbench GEO transport `2b31ba0` remains pushed and unmerged; its independent review is still pending. Do not treat transport libraries as the completed page.
- SEO page-detail slice `e61f1a86690ae3df41303908e82a8c4f7ef48e9c` is pushed from main. It adds only a strict existing-production GET consumer for a page detail after parent tenant/site/page proof; 43 offline tests pass. It is queued for GEO review after PR419/PR425 work and is not mixed into PR419.

## Current ownership and next action

- Coordinator: prepare a narrow `codex/production-sem` promotion for merged workbench PR426 and its reviewed auth/session/read-only prerequisites, without importing unrelated main frontend code. Then mount explicit SEO site and GEO project scope in separate main slices.
- SEM task: freeze PR420 exact `973afb94` while SEO performs final cross-review; after PASS the coordinator merges it and combines it into an independently reviewed production sync.
- SEO task: cross-review SEM PR420 exact `973afb94`; its page-detail slice waits for GEO cross-review.
- GEO task: finish the moving-head PR425 review/fix loop, then review SEO PR419 and SEO page-detail. It must not operate task14 while code review is in progress.

## Human and database queue

- Human: H1 needs one new-version retest only after PR425 is reviewed and deployed. Do not ask for another run before that. The request must specify tenant/task, one generation attempt, expected saved version and brand-warning display, prohibited approval/publishing, screenshots/log time and cleanup.
- Database: no current request. No schema change is in the active work. If one appears, provide table/field purpose, migration and rollback plan, tenant isolation, permissions, data retention and exact executor request before asking the user.

## Monitoring

Automation-2 remains active every five minutes. Routine user report every fifteen minutes; material changes immediately. At this checkpoint all three module owners have bounded work: SEM fixes PR420, SEO re-reviews PR426, GEO re-reviews PR425 and then continues the SEO review queue. No human, database or administrator action is currently required.
