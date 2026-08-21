# SEO independent production pipeline

The SEO production branch is `codex/production-seo`. Feature work must use
`codex/seo-<task-name>` and enter the production branch through a pull request.

## Required checks

`SEO baseline check` runs for every pull request targeting the SEO production
branch and for every push to it. It fails closed when the source diff contains
paths outside the reviewed SEO allowlist. Its required jobs are:

- `SEO / scope-boundary`
- `SEO / backend-tests`
- `SEO / frontend-build`
- `SEO / migration-validation`

Configure these four jobs as required branch checks before enabling releases.

## Release unit

The release writes only these versioned locations:

- `/opt/seo-service/releases/<release>` and `/opt/seo-service/current`
- `/opt/seo-frontend/releases/<release>` and `/opt/seo-frontend/current`

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
4. Include the SEO Nginx locations before the general `/api/` location, then
   run `nginx -t` and reload Nginx.
5. After rollback rehearsal, run
   `sudo bash ops/platform-deploy/install-seo.sh --enable`.
6. Configure the `production-seo` GitHub Environment with required reviewers
   and its SSH secrets.

Do not perform any of these preparation steps from an ordinary code PR.

## Deployment approval report

Before anyone triggers `Production SEO deployment`, report and obtain approval
for all of the following:

- exact `codex/production-seo` commit and merged PRs;
- frontend and backend file scope;
- target directories and services;
- migration revisions introduced since the active release;
- explicit database decision (the workflow always records `migration=not-run`);
- active and previous release identifiers;
- health checks and rollback commands.

The workflow is manual only. It requires `DEPLOY_SEO`, the full expected commit
SHA, all verification jobs, and approval in the `production-seo` Environment.

## Rollback

The restricted deploy module records the previous frontend and backend targets.
If service restart or `/health/seo` fails, it restores both links and restarts
only `seo-service`. For a manual rollback, repoint both SEO `current` links to
the previous matching release and restart only `seo-service`.

Database migrations are never applied by this workflow. If a separately
approved migration is ever executed, its rollback requires a reviewed Alembic
downgrade or a pre-migration database snapshot; changing code symlinks alone is
not a database rollback.
