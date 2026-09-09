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


## Shared SemTask compatibility: current Draft implementation

Development of the actual two-version allowlist is now authorized. PR #369
remains Draft: do not merge, deploy or execute a migration. This supersedes the
current-only/test-patched allowlist described in the historical review notes below.

The runtime allowlist contains exactly `0094_seo_qa_batches` and `0095_sem_tasks`.
The required SEO baseline stays `0094_seo_qa_batches`. A healthy result requires
exactly one allowed revision row AND the existing necessary SEO structure checks.
Unknown, empty, duplicate or multiple rows fail, including a row for each of the
two individually allowed versions. Tests use the actual allowlist without patching.
Missing tables/columns, integer/JSONB mismatches and catalog errors still fail.

Source contract: #370 at `a62a003262f53fab1d1e8ec69175e747266b9469`, direct
parent `0094_seo_qa_batches` to target `0095_sem_tasks`. Relative to reviewed
`66455f1`, only execution-design documentation, a read-only preflight script and
its offline tests were added; candidate migration, source lock, builder and env
are unchanged. The preflight script has not been executed by this SEO task.
This is compatibility implementation, not approval of the production executor.

### Separate approval and rollback requirements

1. Independently approve and deploy the SEO compatibility release first. Record
   its exact commit, artifact checksum and successful health result against the
   current 0094 database. Development approval is not deployment approval.
2. Before separately approving the database migration, retain an independently
   reviewed, tested and deployable rollback artifact that also accepts BOTH 0094
   and 0095 and preserves the required structure checks. Record its exact commit
   and checksum in the release record. No rollback artifact is designated by
   this Draft, and a generic previous-release symlink is insufficient evidence.
3. Only after separate migration approval may the database advance to 0095.
   After that, never roll SEO back to an older 0094-only health checker (including
   backend baseline `4e83611`). Application rollback must use the recorded
   compatible artifact; do not stamp/downgrade the version table or drop SemTask
   audit data to make an older application appear healthy.
4. If no eligible rollback artifact is available, the migration is not ready
   for execution approval. Shared schema reconciliation, production execution
   review and SemTask enablement remain separate gates.

## Historical review log (superseded where noted above)

## Shared SemTask revision compatibility review — 2026-09-06 (DRAFT — awaiting shared migration review)

The latest SEM confirmation supersedes the earlier framework release instruction.
PR #369 must remain Draft: do not merge, deploy or execute a migration. The
allowlist stays current-only until the formal version contract is reviewed.
The current database and SEO baseline are `0094_seo_qa_batches`. SEM has now
submitted candidate `0095_sem_tasks`, parent `0094_seo_qa_batches`, in Draft
[PR #370](https://github.com/DoraHai/ai_sni/pull/370), commit
`d587ac47b737f342960a5b1bd1c2aa3202c4a01c`. These are candidate identifiers,
not an approved formal migration contract. Do not rewrite deployed history.

The health implementation keeps `required_schema_revision` as the SEO baseline,
adds a code-reviewed explicit `compatible_schema_revisions` set, requires exactly
one Alembic version row, and rejects empty, duplicate, multiple, stale and unknown
versions. For now the set contains only 0094. Tests patch the set to simulate the candidate 0095; the actual application
allowlist still rejects 0095. This does not grant approval for the candidate.

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

Remaining gates for accepting the SemTask migration target:

1. The shared migration owner identifies the exact target revision/down_revision,
   migration source commit and reviewed additive DDL (including lineage evidence).
2. Review compatibility and add only that exact target to the allowlist after review;
   the candidate value is already exercised using a test-only patched allowlist.
3. Test current and target structures, missing critical fields, unknown and multiple
   revision rows. The current unit tests exercise the algorithm only; they are not
   acceptance of the candidate SemTask target or execution of its migration.
4. Independently authorize deployment of the compatibility release, then independently
   authorize the shared migration. This Draft does not satisfy target-version
   compatibility or authorize deployment or database changes. Do not roll the
   application back to a 0094-only health checker after advancing the database;
   retain an explicitly compatible rollback release, and do not stamp/downgrade the
   shared version table to make an incompatible application look healthy.

SEM handoff reviewed: `SEM_TASK_SCHEMA_COMPATIBILITY_REVIEW_REQUIRED.md` and
`SEM_TASK_MIGRATION_EVIDENCE_UPDATE_20260906.md` in the local sem-acceptance-results
folder. The contacted task "1.0" clarified it is GEO and cannot confirm SemTask's
owner or migration IDs. Shared-owner confirmation remains outstanding.


Earlier SEM confirmation received for PR #369 (identifier status superseded below):

- Revision is unassigned. `0094_seo_qa_batches` remains a candidate parent, not an
  approved `down_revision`.
- Reviewed DDL draft: [PR #363](https://github.com/DoraHai/ai_sni/pull/363), main
  commit `e6a5185c750bd79b7eb25a096e0fa711db3b8311`, file
  `docs/SEM_TASK_SCHEMA_REVIEW.sql`. It is not a formal Alembic migration.
- Intended scope: add `sem_tasks`, its sequence, indexes and constraints only;
  no SEO table or customer data changes. Tenant FK uses `ON DELETE RESTRICT`.
- Keep #369 Draft and do not add a target revision. SEM will provide the exact
  version contract after formal migration and shared-history integration review.
- #369 was restored to Draft before merge; no deployment or migration was executed.


### Candidate review update: Draft #370

The candidate file is `docs/migration_proposals/0095_sem_tasks.py`, outside the
formal migration directory. SHA-256 of its raw bytes at the pinned commit:
`e3fba9e91dc09500943ecf4c7909ac6e17da84b56fabfa480530040387047e1d`.
Static AST inspection found only one create_table call (`sem_tasks`) and two
create_index calls (`ix_sem_tasks_action`, `ix_sem_tasks_queue`) in upgrade.
No SEO table alteration or customer-row mutation is present. Tenant foreign key
RESTRICT means tenants with SemTask references cannot be deleted; this shared
behavior is intentional in the proposal and must remain part of owner review.

Combining the candidate with the SEO migration graph pinned at
`4e83611aabc8c3d9bb6ecee1a6aff37a2fbfbe21` produces a single head
`0095_sem_tasks`, with no duplicate revisions or missing parents. This is a
static graph result, not evidence that historical migrations were executed.
The shared main and SEO histories differ around 0087; the final shared package,
source checksums and lineage integration still require review. The runner must
also pin/verify the intended schema/search_path, since the candidate uses
unqualified table names. Do not copy it into the formal tree before those gates.

Unit tests cover candidate acceptance only with a patched allowlist, rejection
of missing tables/columns, incorrect integer/JSONB types and catalog denial at
both versions, and rejection of 0095 by the unchanged runtime allowlist.
No candidate code was imported or executed for this static review; no Alembic,
DDL, version-table change, merge or deployment was performed. PR #369 remains Draft.


### Independent SEO source review: #370 at 66455f1

Reviewed exact commit `66455f1f81c1eee69db9e75369930534ceb7bb92`:
`ops/sem-task-migration/SOURCE_LOCK.json`, builder/verifier, local-only env,
rehearsal tests and candidate. Independently compared all 116 locked files with
Git blobs at `4e83611aabc8c3d9bb6ecee1a6aff37a2fbfbe21`; all SHA-256 values
match, including the complete inventory of 111 historical migration files.
The candidate bytes and SHA-256 are unchanged from the preceding review.
Static graph inspection confirms the sole head `0095_sem_tasks` and direct
parent `0094_seo_qa_batches`, with no duplicate IDs or missing parents.

SEO source-level conclusion: no blocking issue found in the pinned independent
source package or the proposed one-step contract. Keeping this package separate
from main avoids rewriting the conflicting historical 0087 parent. This finding
is scoped to these exact source bytes, not approval of historical execution
provenance, production schema reconciliation or migration execution.

The verifier checks complete inventory and hashes before Alembic imports;
the runner fixes the one-step target, rejects other starting revisions and
existing target objects, and uses one transaction with bounded lock/statement
waits. The provided entry is explicitly local-only, not a production runner.
Independent no-database test run: 4 passed, 11 explicitly skipped. Actual local
Alembic rehearsals reported by SEM were inspected in source, not re-executed
by this SEO review. No production or local database was connected.

Next gates remain current-schema reconciliation, review of a production entry
and operational prerequisites, and explicit release/execution authorization.
#369 remains Draft with its 0094-only runtime allowlist; candidate compatibility
is still simulated only in tests. No merge, deployment or migration occurred.

## Shared migration preflight — 2026-09-09

This section is a source-only implementation preflight for the confirmed
production starting point `0094_seo_qa_batches`. It did not connect to
`sem_prod`, create a database, run DDL, stamp a revision, or change any SEM/GEO
business model.

### Authoritative 0094 ancestry

At production SEO baseline `0867004478504ce6d5b848338af4b4dc420556f9`,
`ScriptDirectory.get_heads()` returns the single head
`0094_seo_qa_batches`, `get_base()` returns `0001_initial`, and walking from
0094 to base visits 111 unique revisions. Alembic loads the graph without a
duplicate revision or missing-parent error. The six merge points that close
every historical branch are:

| merge revision | parents |
| --- | --- |
| `0055_merge_geo_platform` | `0038_oauth_account_tenants`, `0054_geo_opt_hierarchy` |
| `0064_merge_geo_sem_heads` | `0064_fact_business`, `0063_seo_serp_brand_assets` |
| `0072_merge_login_seo` | `0071_login_lockout`, `0071_seo_distribution` |
| `0074_merge_geo_seo_heads` | `0073_geo_schema_repair`, `0073_seo_distribution_variants` |
| `0077_merge_sem_seo_heads` | `0076_oauth_rebind_intent`, `0075_seo_content_source_page` |
| `0086_seo_index_review_merge` | `0084_seo_crawl_queued_status`, `0085_seo_page_index_reviews` |

The final linear tail is
`0086 -> 0087 -> 0088 -> 0089 -> 0090 -> 0091 -> 0092 -> 0093 -> 0094`.
The existing `test_seo_migration_merge.py` also fixes the exact upgrade plan
from SEM revision `0076_oauth_rebind_intent` to 0094 and verifies the merge
parents above.

SEM revision `0076_oauth_rebind_intent` is therefore an ancestor of 0094 via
`0077_merge_sem_seo_heads`. Its parents `0075_sem_asset_sync_state` and
`0074_suggestion_workflow` are also present. GEO merge revision
`0074_merge_geo_seo_heads` is an ancestor of both sides joined at 0077, and its
`0073_geo_schema_repair` parent is present. The similarly numbered
`0074_suggestion_workflow` is a distinct SEM revision and is also included.
Do not identify a revision by its numeric prefix alone.

### Empty database executability and known blockers

The source graph is structurally complete for an online `base -> 0094`
upgrade. The repair migrations that use pre-existing tables are ordered after
their table-creating ancestors: `0065_seo_rewrite_schema_repair` follows the
SEO foundation, `0073_geo_schema_repair` follows the GEO hierarchy, and
`0078_seo_site_data_repairs` follows the site-scoped SEO tables. Their data
updates, along with the backfills in 0038/0066/0070/0071/0078/0084, are
expected to be no-ops on an empty database.

This is not yet proof of online execution. No isolated PostgreSQL upgrade from
an empty database was run in this review. In addition, offline SQL generation
is not a substitute: `alembic upgrade 0094_seo_qa_batches --sql` exits at
`0048_clean_legacy_geo_demo_text` because its `op.get_bind().execute(...)`
returns no result in offline mode and `.mappings()` raises `AttributeError`.
0049 uses the same result-reading pattern. The generated SQL stream is partial
and must never be executed. The required proof is a disposable PostgreSQL 16
online rehearsal using the exact migration source.

### Existing and proposed objects

The formal 0094 directory contains neither `sem_tasks` nor
`demo_tenant_bindings`. The reviewed 0095 proposal adds only `sem_tasks`, its
implicit `sem_tasks_id_seq` and `sem_tasks_pkey`, indexes
`ix_sem_tasks_action`/`ix_sem_tasks_queue`, eight `ck_sem_tasks_*` checks, and
the tenant foreign key with `ON DELETE RESTRICT`. None of those identifiers is
created by the 111-revision 0094 ancestry. The confirmed production read-only
preflight likewise reports these SemTask objects absent, so there is no known
object-name conflict at the recorded starting point.

There is no reviewed `demo_tenant_bindings` DDL, model, constraint inventory,
or source lock yet. Its exact conflict set cannot be claimed clean until those
names and column/FK types are fixed and compared with `pg_class`,
`pg_constraint`, and `pg_indexes`. The existing `tenants.id` type in the base
migration is BIGINT, matching the SemTask proposal. A future binding table must
reference that same type and must not introduce a second Alembic version table
or a module-local migration root.

### Reserved single linear sequence

The only acceptable next sequence is:

1. `0095_sem_tasks`, `down_revision = "0094_seo_qa_batches"`.
2. `0096_demo_tenant_bindings`, `down_revision = "0095_sem_tasks"`.

Do not allocate both migrations as children of 0094, reuse module-local 0076 or
0074 identifiers, or add a merge revision after creating parallel heads. The
0096 identifier is a reservation, not approval of its unreviewed DDL. Before
0096 can run, every service health allowlist that may serve that database must
be reviewed to accept the exact new head while retaining required-structure
checks. Deploying 0095-compatible code does not imply 0096 compatibility.

### Required database rehearsals

All destructive work below is restricted to a disposable local database. No
step may target `sem_prod` or a production hostname.

**Fresh empty database:** create a PostgreSQL 16 database with an empty public
schema; record server/search path/role; run the exact shared source online from
base to 0094; assert one `alembic_version` row at 0094, all 111 revisions
reachable, required SEO/SEM/GEO structures present, FKs/indexes/checks valid,
and no unexpected schema. Then install the reviewed 0095 and 0096 files in
order and execute each exact target separately, catalog-diffing only its
approved objects.

**Second no-op:** at each target, capture schema and row-count fingerprints,
run `alembic upgrade <same-target>` again, and require identical revision,
catalog, ownership, grants, sequence state and row counts. No migration body
may execute twice and no additional head may appear.

**Existing sem_prod-shaped upgrade:** restore a verified sanitized schema-only
snapshot whose recorded revision and required structures both match 0094;
verify one version row and absence of every target object; capture owners,
grants, constraints, indexes and sentinel row counts; execute only 0095, then
only 0096 after its separate approval; verify existing objects/data are
unchanged and only the approved objects were added. The real `sem_prod` remains
read-only until this rehearsal, backup/PITR evidence and an execution window
are separately approved.

**Drop/rebuild determinism:** drop only the disposable database, recreate it,
repeat the full online sequence with the same source and role, and compare the
normalized catalog fingerprint with the first run. This is the rollback test
for an empty demo database. Do not use `alembic downgrade` as the rebuild path:
the reviewed SemTask proposal intentionally refuses destructive downgrade and
task audit data must not be dropped after use.

Blocking inputs before implementation are the final source-locked 0095 file,
reviewed 0096 DDL/object inventory, service-role ownership and grants, and the
disposable PostgreSQL online rehearsal. The dual-data-source runtime and demo
tenant authorization remain separate application reviews.
