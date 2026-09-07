# Workbench readonly network boundary

This is a host-injected transport for `createSemReadonlyClient`, not an activated
production connection. No login, token persistence, demo fallback or business writes.
The four reviewed SEM cockpit GET paths and SEM identity preflight are enabled.
Six SEO GET resources are enabled with route-specific query keys and required
tenant/site scope. Review history uses tenant scope plus a verified content reference;
it must not pretend an ignored site_id parameter provides server-side site isolation.
Publication reads require a content ID and cannot use filtered subsets as totals.
GEO routes remain pending integration. This does not activate any UI or grant access.

The browser host must supply its **own HTTPS origin**, `fetch`, and a synchronous
`getSession()` returning `{ token, revision }` from the ordinary authenticated session.
The revision must change on tenant/user/permission changes, even if the token does not.
On logout or context change, call both transport `invalidate()` and SEM client
`invalidate()`, and clear cards, conversation-derived data and search context.
Use the SEM client's verified identity/module context before reading anything.
This transport is not a substitute for server authorization or module qualification.

The demo's module picker cannot grant access. Never feed it into the real permission
context. Never supply an administrator key or use this module as an arbitrary proxy.
The returned response intentionally exposes only `ok`, `status`, and guarded `json()`.

Run offline: `node --test integrations/workbench/readonly-transport.test.mjs`

`view-state.mjs` provides page-local card and discussion-reference lifecycle. It is
not yet mounted on the formal page. Register its `invalidate()` with the host
session adapter; also invalidate on account/date/site changes. Begin a card read
before fetching to clear its prior data immediately. Supply already-authorized,
validated metrics with the returned view revision. Use that same view revision
for `MetricEvidenceCard`; do not mix it with the session adapter's revision.
On permission failure invalidate the module/host authorization and clear the page,
not merely the failed card. Discussion UI must resolve references at render/send
time and remove any copied answers or text containing old evidence on invalidation.
This state does not validate module responses or prove a user has access.

Run lifecycle regressions: `node --test integrations/workbench/view-state.test.mjs`.
