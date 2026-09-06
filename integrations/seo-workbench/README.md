# SEO workbench readonly consumer

This browser-side consumer composes only the six reviewed SEO GET resources:
content assets, review history, per-content publications, publication attempts,
site pages, and latest image evidence. The host must provide an authenticated
GET-only transport and a context already verified as `{tenantId, siteId,
userId, authorizationRevision, allowedReads}`.

The required ordinary account permissions are `seo.content:view` for content,
review and publication reads, and `seo.site:view` for page and image evidence.
The tenant must also have an active or trial SEO module. This client does not
select a tenant or the first available site, and it never uses an administrator
key.

`authorization-context.mjs` resolves that context from the host-injected
transport. It requires an explicit tenant and site selected by the user, then
checks `/api/v1/auth/me`, `/api/v1/auth/modules`, and
`/api/v1/auth/tenants?module=seo`. SEM availability never qualifies SEO access.
It uses a one-row content list as the site ownership probe when `seo.content` is
readable, otherwise a one-row page list when `seo.site` is readable. Both server
routes validate tenant, active SEO module and `site_id` before returning data,
so an empty HTTP 200 is valid evidence only for that selected site's ownership
and the one permission used by the probe. It does not validate detail routes or
claim that every SEO permission was exercised. A 403 means scope/module/menu
access is unavailable; a 404 means the selected site is absent from that tenant,
and the resolver does not try a different site as a fallback.
Without either permission the resolver refuses to create a context. It does not
request `seo.assets` or discover/select a site.

The authorized wrapper invalidates older concurrent connects and the readonly
consumer on reconnect or logout. The host must still call `invalidate()` whenever
its session revision changes. The resolver receives transport and session
invalidation from the host; it never reads or persists a token itself.

Parent references are deliberately sequential:

1. Read `contents` before review history or publications.
2. Read a content's `publications` before any publication attempts.
3. Read `pages` before image evidence.
4. Supply `pageBinding` to `snapshot()` only when the workbench already has an
   explicit, reviewed content/publication URL-to-page mapping.

Review history has no `site_id` request parameter. The client therefore allows
it only for a content ID already observed in the current tenant/site content
response. Attempts and image evidence use the same verified-parent rule because
their response envelopes do not echo the complete scope.

An empty HTTP 200 response remains an empty list. A 401/403 clears the current
context; 404 remains a missing association; server, network and contract errors
remain unavailable. No failure becomes demo data or a zero metric. Publication
lists are unpaginated because that is the current server contract. The consumer
reads the complete publication set for one verified content record and rejects
status-filtered subsets, because a subset cannot drive an all-platform count or
the "approved, pending publication" label.

Starting a new content or page list read revokes the previously verified visible
set and its descendants, including when the new result is empty or fails. A new
publication read likewise revokes the prior publication and attempt set for that
content. This prevents paging, filtering, deletion, or a late child response from
turning a record that was once observed into a permanent authorization cache.
The host must clear the corresponding rendered detail panel, selected object and
conversation-derived references when it starts one of these refreshes. Clearing
the consumer's internal maps cannot remove data that the host already copied into
the DOM or another UI store.

`snapshot()` keeps review, publication, page checking and search performance
separate. Page `assessment_state=assessed` does not become a whole-page pass;
`passed` remains `null`. Article clicks also remain `null`. Latest image evidence
does not prove that the whole page passed, and this client does not use the
site-wide internal-link inventory as article-level acceptance evidence.

Run the offline tests:

```powershell
node --test integrations/seo-workbench/readonly-client.test.mjs
```
