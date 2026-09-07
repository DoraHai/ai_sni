# SEM core cross-audit — 2026-09-07

## Scope and baselines

This was a read-only/offline audit. No Baidu API writes, production changes, credential changes, migrations, or deployments were performed.

- shared baseline: `origin/main` at `9fc891e4c596e92e2af0ab5c567fc3f505c21d62`
- SEM frontend production baseline: `origin/codex/production-sem` at `b07e32da052159d6f38aed245a43f6128945f038`
- SEM backend production baseline: `origin/codex/production-sem-backend` at `22fcb30a0509378f0e347559004ffb79fc937500`
- GEO production baseline inspected for shared-auth behavior: `origin/codex/production-geo` at `36b1b23e3153d50abc61e7b9e7dac6cee59c98eb`

## Blocking and high-priority findings

### P1 — non-funds live writes lose durable intent and misclassify uncertain results

Affected scopes include keyword pause/match/create, negative words, campaign pause/schedule/region, adgroup pause, and landing URL. Their implementations in `app/baidu/writeback.py` create a `pending` row and call `flush()`, then invoke the remote API before any commit. They also catch `BaiduAPIError` (including `BaiduHTTPError`) or a generic exception and mark the row `failed`.

`BaiduHTTPError` explicitly represents a transport result that does not prove rejection. If Baidu applied the change before a timeout, the local row becomes `failed` and can be retried. If the process stops after the remote call and before the final commit, the audit intent can disappear entirely. The funds-changing paths already show the required pattern: persist the intent before the remote call, and send unknown real-write results to `reconcile` through `_record_writeback_exception`.

Offline runtime reproduction against `apply_pause_writeback` injected `BaiduHTTPError(None, "simulated timeout after send")`. The result was `status="failed"`, with one remote call, one pre-call flush, and only the final commit. No network call was made.

Required before enabling these real scopes:

1. persist a durable intent before the external call;
2. classify transport/unknown real-write outcomes as `reconcile`;
3. prevent retry while an unresolved equivalent intent exists;
4. add action-specific idempotency or reconciliation tests, including process interruption boundaries.

### P1 — tenant/account switch can render a late response under the new context

The affected SEM views do not consistently guard asynchronous results with both a request generation and the captured tenant/account identity:

- `frontend/src/views/optimize/SearchTermsView.vue`
- `frontend/src/views/manage/AccountBudgetView.vue`
- `frontend/src/views/manage/CampaignManageView.vue`
- `frontend/src/views/optimize/KeywordWorkbenchView.vue`

When context A is slow and the operator switches to context B, A can finish later and overwrite B's display. Backend tenant enforcement remains in place, but the UI can display the prior context and subsequent actions can be prepared with current context parameters. `AdgroupManageView.vue` already contains a suitable `loadGeneration` pattern.

Required fix: capture tenant/account at request start, invalidate all prior generations on context/auth change, and accept a result only when generation and captured identities still match.

### P1 — search-term refresh and displayed window are ambiguous with multiple accounts

`app/api/search_terms.py` selects the first active account for manual synchronization without an account parameter or an ambiguity error. The synchronization code replaces only that account's snapshot. The list endpoint then aggregates the entire tenant while returning a window from an unordered single row.

For a tenant with two active accounts and different report windows, one account can be refreshed while totals remain mixed and are labelled with one arbitrary window. The cockpit endpoint already models this condition with `mixed_windows`; the classic endpoint should either require an account or expose the mixed-window state explicitly.

### P1 — shared persistent-session candidate still accepts a transient mixed identity

Cross-review target: `codex/session-storage-sync-20260907` at `453aa6cabd600e939d9449aa7e24d48b78825877`.

The candidate writes the new `sem_user` before the new `sem_token`. Another tab receives the user storage event first, reads local storage, and accepts the old token together with the new user. An offline event-by-event reproduction returned `token-user-1` paired with user id `2`.

The candidate also clears reactive auth on a cross-tab logout without navigating away from the current protected route, and permission changes do not re-run the current route's permission guard. Loaded protected data can therefore remain visible until navigation or reload. This candidate is not merge-ready until the auth pair has a single atomic/versioned publication point and logout/permission changes invalidate the current view and pending requests.

## Confirmed controls

- Scoped auth validates tenant IDs by type and enforces tenant/module/SEM identity for guarded routes.
- Funds-changing writes use scoped advisory locks, parameter fingerprints, approval consumption, a committed pending intent, unresolved-intent blocking, and independent reconciliation.
- Scheduler account collection uses independent sessions; OAuth refresh also isolates grants by session.
- Cockpit SEM reads expose explicit account scope and mixed search-term windows, with generally correct null-versus-zero semantics.
- Current shared 401 handling clears both browser stores and redirects to login.

## Verification

The focused backend suite completed with `153 passed, 4 skipped`; the four skips are opt-in PostgreSQL cases. The shared-session candidate's own session tests and auth build passed, but the additional event-by-event reproduction exposed the mixed token/user race described above.

These results do not constitute real-account acceptance. Real platform effects, late responses from Baidu, and production browser behavior remain intentionally untested.

## Re-review of non-funds intent candidate

Candidate: `codex/sem-nonfunds-writeback-intents-20260907` at `37e49181d3ee4055ad8a145e53317355c30b0b6c`.

Verdict: **blocked; do not merge or release**.

The candidate correctly commits a live `pending` intent before the remote call and routes unknown exceptions to `reconcile`, but the following execution gaps remain:

1. **A pre-call intent can be reconciled while the executor is reacquiring locks.** The reconciliation API accepts both `pending` and `reconcile`. After the initial intent commit, `_persist_action_intent` reacquires the asset, account, and record locks, but does not verify that the refreshed record is still `pending`. An offline reproduction changed the record to `failed` with `reconciliation_result="confirmed_not_executed"` during that interval. The executor still made one remote call and finished with `status="success"` while retaining `confirmed_not_executed`. The executor must check the refreshed state before sending; the UI/API should also distinguish an actively sending intent from an unknown result.
2. **`addWord` has no unresolved-action gate or request idempotency.** `apply_add_word_writeback` only checks the synchronized keyword dimension. A retry after remote success but before candidate adoption or keyword synchronization can issue another create, as can a concurrent request after the first intent commit. The guard must key at least tenant, account, adgroup, and normalized word, and cover unresolved and recently successful equivalent creates or use a durable request idempotency key.
3. **Conflicting actions use separate gates.** A campaign schedule update with `pause=true` and campaign pause/enable can both pass because one gate only selects `campaign_schedule` and the other only pause/enable action types. Both can call the remote campaign API after their separate intent commits and race on the campaign pause state. Conflict domains must reflect the fields actually mutated.
4. **Post-commit revalidation is incomplete.** Refreshing the asset does not verify that it still belongs to the original account. The add-word duplicate check is not repeated after the commit. Negative-word full-list payloads are calculated before the commit and are not rebuilt from the refreshed snapshot, so a synchronization update in the release/relock interval can be overwritten.

The candidate's focused tests passed (`88 passed`). A full run excluding `tests/test_geo_brand_profile.py` passed with `2091 passed, 47 skipped`. The isolated GEO brand-profile test failed identically on both this candidate and baseline `9fc891e4c596e92e2af0ab5c567fc3f505c21d62`, so it was not introduced by the candidate. The 47 skipped tests do not include a PostgreSQL concurrency test for this change.

The next review requires a disposable PostgreSQL test with two independent sessions. It must prove same-action and cross-action serialization, no-row guard behavior, add-word retry behavior, a reconciliation attempt during the post-commit/relock interval, and correct payload reconstruction after a concurrent snapshot refresh.

### Follow-up candidate `cd8cf8e`

Candidate `cd8cf8ef1cf703d6702c973cde7feb03e67ea42f` remains blocked.

- The record-state check now stops a record that was reconciled in the post-commit interval, and add-word/campaign conflict checks were expanded.
- A landing-URL snapshot check was inserted into `apply_adgroup_pause_writeback` instead of the landing-URL function. It references undefined `old_snapshot`; a live adgroup pause therefore fails after committing its pending intent and before entering the remote-call `try` block. The landing-URL action still lacks the intended post-commit snapshot check.
- The two new PostgreSQL tests execute their sessions sequentially. One commits reconciliation before starting the executor; the other commits a pending row before the second session queries it. They do not test two transactions starting with no pending row, lock waiting, the commit/relock interval, add-word success before candidate/dimension persistence, or a full-list synchronization race.

The focused run was `89 passed, 2 skipped`. Zero skips for these two tests would still be insufficient until they use explicit two-session barriers and exercise the proven races.

## Re-review of shared session candidate

Candidate `codex/session-storage-sync-20260907` at `0ad7b9adf47f9b510a72879303ac4904c58189db` closes the original mixed token/user storage-event race by publishing a single `sem_auth_v1` envelope. It is still blocked:

1. `App.vue` starts `refreshMe`, tenant loading, badges, and writeback-mode loading concurrently. A successful `refreshMe` unconditionally increments `authRevision`, so responses started under the same valid identity are rejected as `AUTH_CONTEXT_CHANGED`. An offline reproduction completed `me`, refreshed the identical user, and then completed the tenant request; the tenant request was rejected. The bootstrap has no retry for this path.
2. Legacy-client logout compatibility is incomplete. When an envelope exists, removing only legacy `sem_token`/`sem_user` keys returns `undefined` from `persistentAuthForEvent`, leaving the envelope valid. An older open tab can log out locally and then recover the supposedly logged-out session from the envelope on reload. The supplied test omits the envelope and therefore does not model a mixed-version rollout.
3. When all SEO permissions are removed, the SEO route decision returns `false`. The revalidation wrapper only replaces truthy non-`true` decisions, so the already rendered protected page remains visible.

The candidate's session tests, workbench-session test, auth build, main build, and SEM build verification all passed in the review environment; those checks do not cover the three paths above.
