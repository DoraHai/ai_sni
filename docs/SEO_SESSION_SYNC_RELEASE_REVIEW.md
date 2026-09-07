# SEO shared-session frontend release review

## Scope

This production-sync candidate ports the reviewed session-storage changes from
main PR #415 onto the current `codex/production-seo` frontend baseline. It keeps
the SEO production routes and pages intact and does not include SEM/GEO views,
backend code, migrations, collection, or publishing changes.

The runtime scope is limited to the shared API client and session store used by
the isolated SEO entry, plus the SEO entry/router hooks that revalidate the
current route when identity or permissions change. The source-boundary list and
frontend-only workflow include the two session regression tests so later SEO
release candidates cannot silently omit them.

## Review evidence

- `npm run test:session-storage`: 5 unit tests and the store/router integration
  scenario pass.
- `npm run build:seo`: the isolated SEO bundle builds successfully.
- `npm run verify:seo-build`: the manifest contains only allowed SEO assets.
- Source route comparison against the current `codex/production-seo` head:
  23 routes before and 23 routes after, with no added or removed route path.
- The production-only task center, Q&A workbench, Q&A legacy route, and Element
  Plus tabs remain present.

## Release order

1. Review this branch as a pull request whose base is
   `codex/production-seo`; do not merge `main` into the production branch.
2. Require the SEO baseline checks, session tests, isolated SEO build, and build
   verifier to pass on the exact candidate SHA.
3. Merge only after explicit SEO frontend deployment approval. The merge push
   starts `Production SEO frontend deployment` and records
   `backend=not-included`, `migration=not-run`, and `service_restart=not-run`.
4. After deployment, verify login/session changes, permission loss redirect,
   `/seo/content/qa`, and `/seo/tasks`. Customer/site data checks remain blocked
   until the cockpit supplies an authorized tenant, site, and read-only identity.

Rollback requires restoring the previous reviewed `codex/production-seo`
frontend commit through the same controlled frontend workflow. It must not run
an Alembic command or restart the SEO backend service.
