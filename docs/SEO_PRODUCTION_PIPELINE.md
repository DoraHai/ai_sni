# SEO independent production pipeline

The SEO production branch is `codex/production-seo`. Feature work must use
`codex/seo-<task-name>` and enter the production branch through a pull request.

## Branch lineage policy

`main` is the only development trunk. SEO feature branches must start from an
approved `main` commit. `codex/production-seo` is a release branch only: it may
receive reviewed SEO promotion PRs, but must not become an independent
development line again.

Both the SEO baseline and production deployment workflows require the release
commit to descend from `origin/main`. A missing merge-base or a release branch
that does not contain the approved main lineage fails before deployment.

The 2026-08-31 convergence uses an explicit no-content history bridge followed
by a separately reviewed SEO semantic-sync commit. Do not repeat an unrelated
history merge or replace shared SEM/GEO files with an older SEO tree.

## Required checks

`SEO baseline check` runs for every pull request targeting the SEO production
branch and for every push to it. It fails closed when the source diff contains
paths outside the reviewed SEO allowlist. Its required jobs are:

- `SEO / scope-boundary`
- `SEO / backend-tests`
- `SEO / frontend-build`
- `SEO / migration-validation`

Merging a reviewed pull request into `codex/production-seo` is the production
authorization for that exact merge commit. A frontend-only push starts
`Production SEO frontend deployment`. A push containing backend or migration
paths starts the full `Production SEO deployment`. Both workflows share one
concurrency group and fail closed if the triggering commit is no longer the
production head.

Configure these four jobs as required branch checks before enabling releases.

## Release unit

The release writes only these versioned locations:

- `/opt/seo-service/releases/<release>` and `/opt/seo-service/current`
- `/opt/seo-frontend/releases/<release>` and `/opt/seo-frontend/current`

The frontend-only release contains no backend directory, records
`backend=not-included`, `migration=not-run`, and `service_restart=not-run`, and
atomically switches only `/opt/seo-frontend/current`. It does not execute
`systemctl`, touch Nginx configuration, or invoke Alembic. The full release is
reserved for reviewed backend or migration-path changes.

It restarts only `seo-service`. It must not restart or write into SEM, GEO,
Diagnostic Center, authentication, or website release units. The backend
archive includes shared Python dependencies required by the SEO router, but
the deployer installs them only under `/opt/seo-service`.

The daily SEO ranking collector remains in the shared scheduler. Moving that
schedule into `seo-service` requires a separate review because changing its
current owner would modify shared SEM runtime code.

## Server preparation

Server preparation is a separate, reviewed operation and is not performed by
GitHub Actions:

1. Review `deploy/seo-service.service` and `deploy/seo-frontend.nginx.conf`.
2. Install the generic restricted `/usr/local/sbin/platform-deploy` helper.
3. Run `sudo bash ops/platform-deploy/install-seo.sh` to install the SEO entry
   in the locked state.
4. After reviewing the frontend-only dispatcher and module, run
   `sudo bash ops/platform-deploy/install-seo-frontend.sh`. This updates only
   the restricted SEO deploy entry and does not reload Nginx, reload systemd,
   or restart a service.
5. Include the SEO Nginx locations before the general `/api/` location, then
   run `nginx -t` and reload Nginx.
6. After rollback rehearsal, run
   `sudo bash ops/platform-deploy/install-seo.sh --enable`.
7. Use the existing `production` GitHub Environment with its restricted
   `DEPLOY_HOST`, `DEPLOY_PORT`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, and
   `DEPLOY_KNOWN_HOSTS` secrets. Do not add a separate required-reviewer
   deployment gate: merge to `codex/production-seo` is the deployment
   authorization.

Do not perform any of these preparation steps from an ordinary code PR.

## Automatic deployment contract

Before merging to `codex/production-seo`, reviewers confirm all of the
following:

- exact `codex/production-seo` commit and merged PRs;
- frontend and backend file scope;
- target directories and services;
- migration revisions introduced since the active release;
- explicit database decision (the workflow always records `migration=not-run`);
- active and previous release identifiers;
- health checks and rollback commands.

The workflows are triggered only by a push to `codex/production-seo`. They check
out the triggering `github.sha`, reruns the SEO backend tests, SEO frontend build
and verification, and the single-head Alembic validation, then packages an
immutable artifact whose manifest records `migration=not-run`.

Deployments are serialized. The workflow checks the remote
`codex/production-seo` head during verification, before server access, before
upload, and immediately before apply. If any newer commit exists, the older job
stops instead of replacing a newer release.

The frontend release workflow validates the immutable SHA and explicit
isolation manifest, rejects backend content, switches only the SEO frontend
link, and verifies `/seo/`, its static assets, the same-origin portal link, and
security headers. The full deploy module validates `migration=not-run`, switches both
SEO release links, and restarts only `seo-service`. `/health/seo` compares the
database Alembic revision with the revision required by the release. A mismatch
returns HTTP 503, so the restricted deployer restores the previous release.
Database migrations are never run automatically; a reviewed migration must be
applied separately before retrying a release that requires it.

## Rollback

The restricted deploy module records the previous frontend and backend targets.
If service restart or `/health/seo` fails, it restores both links and restarts
only `seo-service`. For a manual rollback, repoint both SEO `current` links to
the previous matching release and restart only `seo-service`.

Database migrations are never applied by this workflow. If a separately
approved migration is ever executed, its rollback requires a reviewed Alembic
downgrade or a pre-migration database snapshot; changing code symlinks alone is
not a database rollback.


## Shared SemTask revision compatibility review — 2026-09-06 (DRAFT)

This proposal must not be merged/deployed or used to authorize a migration yet.
The current database and SEO baseline are `0094_seo_qa_batches`. No SemTask target
revision, parent, migration file or responsible shared-migration owner has been
confirmed. `0094_seo_qa_batches` is a candidate parent based on the current single
head, not an approved new migration parent. Do not allocate a guessed `0095` or
rewrite deployed migration history.

The health implementation keeps `required_schema_revision` as the SEO baseline,
adds a code-reviewed explicit `compatible_schema_revisions` set, requires exactly
one Alembic version row, and rejects empty, duplicate, multiple, stale and unknown
versions. For now the set contains only 0094. The test-only target is not a real
migration ID and is never in the application allowlist.

Before reporting healthy, a read-only pg_catalog query follows the connection's
search_path via to_regclass and checks all mapped column names on 12 critical SEO
tables: sites, content assets, AI operations, metric snapshots, image reviews and
verification queue, SEO tasks, and five question/answer tables. Integer widths
(SMALLINT/INTEGER/BIGINT) and JSONB types are checked. Missing tables/columns,
incompatible checked types and catalog errors fail with HTTP 503. This is a
minimum runtime contract, not validation of all indexes, foreign keys, checks,
string lengths, nullability or migration contents; migration review must cover
those separately. Extra columns/tables are allowed only at an explicitly accepted
revision. No new dependency on sem_tasks is introduced.

Validation: 2026-09-06 production read-only transaction, 5-second statement timeout,
12 tables/172 columns, actual single revision 0094, no incompatibilities. No DDL,
version-table writes, customer-row reads, service changes or deployment were used.
An initial test implementation confused SMALLINT with INTEGER inheritance; this
was corrected before PR and covered by a dedicated regression test.

Completion gates:

1. The shared migration owner identifies the exact target revision/down_revision,
   migration source commit and reviewed additive DDL (including lineage evidence).
2. Review compatibility and add only that exact target to the allowlist in this PR;
   replace/supplement the test-only target case with a test for the actual value.
3. Test current and target structures, missing critical fields, unknown and multiple
   revision rows. The current unit tests exercise the algorithm only; they are not
   acceptance of an unassigned SemTask target or execution of its migration.
4. Independently authorize deployment of the compatibility release, then independently
   authorize the shared migration. This PR grants neither approval. Do not roll the
   application back to a 0094-only health checker after advancing the database;
   retain an explicitly compatible rollback release, and do not stamp/downgrade the
   shared version table to make an incompatible application look healthy.

SEM handoff reviewed: `SEM_TASK_SCHEMA_COMPATIBILITY_REVIEW_REQUIRED.md` and
`SEM_TASK_MIGRATION_EVIDENCE_UPDATE_20260906.md` in the local sem-acceptance-results
folder. The contacted task "1.0" clarified it is GEO and cannot confirm SemTask's
owner or migration IDs. Shared-owner confirmation remains outstanding.
