# Current coordination — 2026-09-07 14:13 Asia/Shanghai

User resumed development. Historical pause documents do not represent current instructions.

## Current user instructions

- Continue the workbench and coordinate the three existing SEM, SEO and GEO tasks. Keep their work independent where possible and use cross-review before merge.
- Preserve context in this file with exact commits, test evidence, production evidence, scope boundaries and the next owner/action. Do not infer completion from an idle task.
- Ask the user with a concrete checklist before a database change or required human test. Work that does not depend on either continues.
- Check every five minutes and report routine progress every fifteen minutes; report material failures/completions immediately.
- Usage stop line: Codex primary remaining usage below 20%. At 14:02 the account tool reported used 59%, remaining 41%. Automation-2 checks usage first; below the line it must pause new development/tests/merge/deploy, pause the three module tasks, update this document and notify the user. It must not consume a reset credit automatically.

## Completed releases

- SEM backend PR421: deployed `554934d6cbb2921f10f1fe165cbaf62f5b2544f8`, run `34085269523`. Coordinator independently confirmed public health release_commit and db=ok. Rollback baseline `22fcb30`.
- SEM frontend PR422: deployed `ee3bf6c9077b99836a95f607abd44f2a9ac99264`, run `34084823098`; owner confirmed onboarding/assets and new ledger markers. Rollback baseline `b07e32d`.
- GEO PR423: deployed `8af28f3125cfd4059452d7f5c3067986442eb0a4`, run `34085373873`, verify job `101628285071`, deployment job `101628424440`, successful. Deployment log reports both release directories and migration=not-run. Public geo-health and dashboard 200; db=ok; index-DW6fitbf.js, GeoFactsView-jwuwovqS.js and GeoTaskEditorView-Hedjz-aK.js contain reviewed changes. Rollback baseline `c8883a3`; current server previous symlink not independently inspected.
- GEO independent PG evidence: verify-only `dcfa504`, run `34085251595`, exact 11 names, no skips/failures. Artifact digest `8b0f3c9fbeaaf4db70776f5fdd6a0371c2c34c4e205c7210418d3141127f014d`. Verify-only files were NOT merged. Business SHA was `dc68e9b`.

No migration, task14 generation, publication, or new real writeback test was performed in these releases. H1 human acceptance remains pending on the new release; old failed attempts are not accepted retroactively.

## Active work

- SEM PR420 draft exact `67800555808f3dca333b8cf7713f80af2594a298`: account selection and confirmation/late-response guards are substantially repaired; all current CI is green. Coordinator review remains BLOCKED on one P1: `authRevision` is only part of request guards, while SearchTerms, AccountBudget, CampaignManage, KeywordWorkbench and KeywordDetail do not listen for permission revision changes and therefore can leave already-rendered data visible after access is revoked. SEM is fixing this and adding mounted tests across the affected views. Do not merge/deploy the current SHA.
- SEO PR419 exact `a083b1687612883a5e488d4e8b0660ba84898149`: ready locally, awaiting GEO independent review. Production remains separate from the candidate. SEO also owns selecting one high-priority offline gap from its 34-item mapping; no customer publishing or image feedback wait is required for that selection.
- GEO follow-up PR425: draft exact `bb5868f78e2f685bd8b88ab1767880d8e74fb8c7` onto production GEO `8af28f3`; current CI is green. It now recomputes brand validation from the current Markdown, adds an independent readiness/publishing block even when score gating is disabled, returns brand issues to the editor and shows an explicit warning. GEO is independently re-reviewing this exact SHA. No merge/deploy/task14 action until PASS.
- Workbench view-state PR424 merged to main as `b99479efab18bb9a4146fb03b46510ddd86bdb94` after independent PASS and all CI. Formal page PR426 is draft at exact `e0c282b72b37e7decf4adc647f9aa10b73008785`. The first independent review blocked three P1s; all three were repaired: derived conversation clears on customer/date/auth changes, platform-level module availability is narrowed with module-specific tenant lists before saying a selected customer is open, and local HTTP cockpit preview blocks App and page identity/business reads. Generation/context guards reject late scope results; new offline/scope tests were added. Local production build, SEM build contract, 43 related tests and SEM UI contracts pass. The first post-fix CI failed only because an existing VM test harness lacked the new preview dependency; `e0c282b` repairs that harness and adds zero-call checks. New CI and SEO re-review are pending. It is not merged or deployed.
- Workbench GEO transport `2b31ba0` remains pushed and unmerged; its independent review is still pending. Do not treat transport libraries as the completed page.
- SEO page-detail slice `e61f1a86690ae3df41303908e82a8c4f7ef48e9c` is pushed from main. It adds only a strict existing-production GET consumer for a page detail after parent tenant/site/page proof; 43 offline tests pass. It is queued for GEO review after PR419/PR425 work and is not mixed into PR419.

## Current ownership and next action

- Coordinator: finish PR426 re-review/CI, repair any new finding, then mount explicit SEO site and GEO project scope in separate slices. Keep conversation visually primary and cards expandable; preserve the discovery/explanation boundary.
- SEM task: repair PR420 permission-revocation stale-display P1 with mounted/deferred tests across affected views; return a new exact SHA, no merge/deploy.
- SEO task: re-review workbench PR426 exact `e0c282b`; its page-detail slice waits for GEO cross-review.
- GEO task: re-review PR425 exact `bb5868f`, then finish independent review of SEO PR419, then review SEO page-detail. It must not operate task14 while code review is in progress.

## Human and database queue

- Human: H1 needs one new-version retest only after PR425 is reviewed and deployed. Do not ask for another run before that. The request must specify tenant/task, one generation attempt, expected saved version and brand-warning display, prohibited approval/publishing, screenshots/log time and cleanup.
- Database: no current request. No schema change is in the active work. If one appears, provide table/field purpose, migration and rollback plan, tenant isolation, permissions, data retention and exact executor request before asking the user.

## Monitoring

Automation-2 remains active every five minutes. Routine user report every fifteen minutes; material changes immediately. At this checkpoint all three module owners have bounded work: SEM fixes PR420, SEO re-reviews PR426, GEO re-reviews PR425 and then continues the SEO review queue. No human, database or administrator action is currently required.
