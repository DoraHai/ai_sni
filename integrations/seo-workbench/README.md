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
lists are unpaginated because that is the current server contract.

`snapshot()` keeps review, publication, page checking and search performance
separate. Page `assessment_state=assessed` does not become a whole-page pass;
`passed` remains `null`. Article clicks also remain `null`. Latest image evidence
does not prove that the whole page passed, and this client does not use the
site-wide internal-link inventory as article-level acceptance evidence.

Run the offline tests:

```powershell
node --test integrations/seo-workbench/readonly-client.test.mjs
```
