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
