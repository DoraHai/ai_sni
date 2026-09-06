# Workbench readonly network boundary

This is a host-injected transport for `createSemReadonlyClient`, not an activated
production connection. No login, token persistence, demo fallback or business writes.
Only the four reviewed SEM cockpit GET paths are enabled. SEO/GEO and identity routes
require their own reviewed contracts before inclusion.

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
