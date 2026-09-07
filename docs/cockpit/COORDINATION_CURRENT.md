# Current coordination — 2026-09-07 13:43 Asia/Shanghai

User resumed development. Historical pause documents do not represent current instructions.

## Current user instructions

- Continue the workbench and coordinate the three existing SEM, SEO and GEO tasks. Keep their work independent where possible and use cross-review before merge.
- Preserve context in this file with exact commits, test evidence, production evidence, scope boundaries and the next owner/action. Do not infer completion from an idle task.
- Ask the user with a concrete checklist before a database change or required human test. Work that does not depend on either continues.
- Check every five minutes and report routine progress every fifteen minutes; report material failures/completions immediately.
- Usage stop line: Codex primary remaining usage below 20%. At 13:33 the account tool reported used 57%, remaining 43%. Automation-2 now checks usage first; below the line it must pause new development/tests/merge/deploy, pause the three module tasks, update this document and notify the user. It must not consume the available reset credit automatically.

## Completed releases

- SEM backend PR421: deployed `554934d6cbb2921f10f1fe165cbaf62f5b2544f8`, run `34085269523`. Coordinator independently confirmed public health release_commit and db=ok. Rollback baseline `22fcb30`.
- SEM frontend PR422: deployed `ee3bf6c9077b99836a95f607abd44f2a9ac99264`, run `34084823098`; owner confirmed onboarding/assets and new ledger markers. Rollback baseline `b07e32d`.
- GEO PR423: deployed `8af28f3125cfd4059452d7f5c3067986442eb0a4`, run `34085373873`, verify job `101628285071`, deployment job `101628424440`, successful. Deployment log reports both release directories and migration=not-run. Public geo-health and dashboard 200; db=ok; index-DW6fitbf.js, GeoFactsView-jwuwovqS.js and GeoTaskEditorView-Hedjz-aK.js contain reviewed changes. Rollback baseline `c8883a3`; current server previous symlink not independently inspected.
- GEO independent PG evidence: verify-only `dcfa504`, run `34085251595`, exact 11 names, no skips/failures. Artifact digest `8b0f3c9fbeaaf4db70776f5fdd6a0371c2c34c4e205c7210418d3141127f014d`. Verify-only files were NOT merged. Business SHA was `dc68e9b`.

No migration, task14 generation, publication, or new real writeback test was performed in these releases. H1 human acceptance remains pending on the new release; old failed attempts are not accepted retroactively.

## Active work

- SEM PR420: three P1 groups remain blocked: account-change stale data/actions, confirmation-dialog context races, implicit first-account selection. SEM active on fixes; do not mix with already released nonfund intents.
- SEO PR419 exact `a083b1687612883a5e488d4e8b0660ba84898149`: ready locally, awaiting GEO independent review. Production remains separate from the candidate. SEO also owns selecting one high-priority offline gap from its 34-item mapping; no customer publishing or image feedback wait is required for that selection.
- GEO follow-up PR425: draft from exact `47cbcc0862552c162263f53f009516667a55d9f2` onto production GEO `8af28f3`. It allows only `rules_after_claim_guard` evidence-only drafts to persist with explicit failed brand validation when the configured category/brand has no support in eligible facts. Ordinary AI draft brand enforcement must stay hard. SEO cross-review and exact-head CI are pending. No task14 action.
- Workbench view-state PR424 merged to main as `b99479efab18bb9a4146fb03b46510ddd86bdb94` after independent PASS and all CI. Formal page development moved to `codex/workbench-cockpit-shell` from that main. Current uncommitted slice adds protected `/workspace/cockpit`, a discoverable entry, central guided conversation, action ledger, responsive module layout and real HTTPS SEM report reading through the reviewed ordinary-session/preflight/transport clients. SEO/GEO show scope-required state until their business-object selection is safely mounted. No fake metrics; unavailable phone data is labelled unavailable. Production build, SEM build contract, session/evidence tests and 25 underlying client/lifecycle tests pass. It is not committed, reviewed, merged or deployed yet.
- Workbench GEO transport `2b31ba0` remains pushed and unmerged; its independent review is still pending. Do not treat transport libraries as the completed page.

## Current ownership and next action

- Coordinator: finish the formal page slice, add reviewable interaction coverage, commit and request independent review. Keep the conversation visually primary and data cards expandable; preserve the discovery/explanation boundary.
- SEM task: repair PR420's three P1 groups with mounted/deferred component tests. Its latest turn hit a task usage limit after starting; it has been requeued once and must not repeat already completed releases.
- SEO task: cross-review GEO PR425, then resume its chosen offline SEO gap and later consume the GEO review of PR419.
- GEO task: finish independent review of SEO PR419 and provide PR425 exact CI evidence. It must not operate task14 while code review is in progress.

## Human and database queue

- Human: H1 needs one new-version retest only after PR425 is reviewed and deployed. Do not ask for another run before that. The request must specify tenant/task, one generation attempt, expected saved version and brand-warning display, prohibited approval/publishing, screenshots/log time and cleanup.
- Database: no current request. No schema change is in the active work. If one appears, provide table/field purpose, migration and rollback plan, tenant isolation, permissions, data retention and exact executor request before asking the user.

## Monitoring

Automation-2 remains active every five minutes; prompt updated to these release facts. Routine user report every fifteen minutes; material changes immediately. This check saw SEM active and SEO/GEO idle; assigned bounded pending reviews to the idle owners, without restarting SEM. No new human or administrator action requested this check.
