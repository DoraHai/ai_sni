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

Merging a reviewed pull request into `codex/production-seo` is the production
authorization for that exact merge commit. The resulting push automatically
starts `Production SEO deployment`; there is no separate manual dispatch or
deployment approval step.

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
6. Use the existing `production` GitHub Environment with its restricted
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

The workflow is triggered only by a push to `codex/production-seo`. It checks
out the triggering `github.sha`, reruns the SEO backend tests, SEO frontend build
and verification, and the single-head Alembic validation, then packages an
immutable artifact whose manifest records `migration=not-run`.

Deployments are serialized. The workflow checks the remote
`codex/production-seo` head during verification, before server access, before
upload, and immediately before apply. If any newer commit exists, the older job
stops instead of replacing a newer release.

The deploy module validates the immutable SHA and `migration=not-run`, switches
only the SEO backend and SEO frontend release links, and restarts only
`seo-service`. Database migrations are never run automatically.

## Rollback

The restricted deploy module records the previous frontend and backend targets.
If service restart or `/health/seo` fails, it restores both links and restarts
only `seo-service`. For a manual rollback, repoint both SEO `current` links to
the previous matching release and restart only `seo-service`.

Database migrations are never applied by this workflow. If a separately
approved migration is ever executed, its rollback requires a reviewed Alembic
downgrade or a pre-migration database snapshot; changing code symlinks alone is
not a database rollback.
