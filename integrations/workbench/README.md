# Workbench readonly network boundary

This is a host-injected transport for `createSemReadonlyClient`, not an activated
production connection. No login, token persistence, demo fallback or business writes.
The four reviewed SEM cockpit GET paths and SEM identity preflight are enabled.
Six SEO GET resources are enabled with route-specific query keys and required
tenant/site scope. Review history uses tenant scope plus a verified content reference;
it must not pretend an ignored site_id parameter provides server-side site isolation.
Publication reads require a content ID and cannot use filtered subsets as totals.
GEO customer lookup and six reviewed resources are enabled with exact paths and
per-route query keys. Each data request requires tenant scope; weekly resources
also require an explicit valid Monday week end. Questions retain their own filters
without pretending to follow the weekly metric window. Legacy configuration and
job routes are excluded. This does not activate any UI or grant access; GEO identity
preflight and full host wiring still require integration review.

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
