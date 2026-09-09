# SEO demo fixture loader

This loader is an offline, single-use control for an isolated SEO demonstration
database. It does not crawl, generate data, create a tenant binding, change
grants, run a migration, or contact an external service.

## Bundle contract

A bundle is a directory containing `manifest.json` and one UTF-8 JSONL file per
declared table. The manifest is exact-schema JSON and records:

- module `seo`, schema version `1`, target database `gsnipers_demo`, and target
  revision `0098_demo_binding_no_truncate`;
- immutable `dataset_key` and `dataset_version`, demo tenant id, loader version,
  generation time and the already-created application read-only role;
- site ids and canonical domains;
- source URLs, collection timestamps and source-content SHA-256 values;
- exact `text_policy={synthetic:true,redacted:true,policy_version:seo-fixture-text-v1}`;
- each table file's normalized relative path, byte size, SHA-256 and row count;
- a `bundle_sha256` over the canonical manifest excluding that field itself.

Only `tenants`, `tenant_modules`, and tables whose names are explicitly listed
in `app.seo_demo_fixture_loader.TABLE_ORDER` are accepted. `tenants`,
`tenant_modules`, and `seo_sites` are required. SEM/GEO tables, undeclared files,
absolute or parent paths, symlinks, unknown columns, credentials, cross-tenant
rows, undeclared site ids, and runnable job states are rejected before a
database connection is needed.

Columns are allowed per table rather than inferred from the ORM. Credential
keys and scalar values include authorization, API/OAuth/client secrets, private
and access keys, sessions, Bearer/JWT/common provider tokens. Direct contact
data and labelled person/address/telephone text are rejected. The five supported
tables whose schema requires an actor use only the fixed synthetic identities
documented in the loader; ordinary business names and public webpage copy remain
valid under the declared synthetic/redacted policy.

Every `seo_sites.site_settings` object must contain the manifest dataset key and
version as `fixture_marker` and `dataset_version`, plus JSON booleans
`synthetic=true`, `scheduler_excluded=true`, and
`external_actions_disabled=true`. Distribution connection examples must have no
encrypted credentials, `has_credentials=false`, and `enabled=false`.

## Database transaction

Execution requires explicit allowlists for both the URL hostname and the server
address returned by PostgreSQL. The URL, connected database and manifest must
all name `gsnipers_demo`; `sem_prod` is rejected. The loader requires one exact
Alembic revision, `0098_demo_binding_no_truncate`, a non-superuser,
non-replication loader role, and SERIALIZABLE isolation.
Both the loader and application roles must prove they have no `CONNECT` on
`sem_prod` using the PostgreSQL catalog from the demo connection. Missing or
failed catalog evidence is a hard failure; the loader never connects to the
production database to perform this check.

A fixed, database-wide SEO fixture advisory lock serializes every dataset. All
allowed data tables, users, roles and both demo-binding tables must be empty. The latter are control-plane
objects and are never written by this loader. Inserts use SQLAlchemy metadata,
the fixed table order and explicit manifest rows; no update, upsert, delete,
truncate, DDL or sequence adjustment is performed. Any validation or insert
failure rolls back the whole transaction.

Before and after insertion, the declared application role must have SELECT and
no INSERT, UPDATE, DELETE or TRUNCATE privilege on every allowed table. It must
have public schema USAGE but no schema CREATE, database CREATE/TEMP, superuser,
replication, or writable sequence privilege. Row counts are compared with the
bundle before commit.

The loader also requires the immutable database receipt registry described in
`docs/SEO_DEMO_FIXTURE_RECEIPT_MIGRATION_PROPOSAL.md`. That registry is not part
of revision `0098`, so both load and receipt-recovery entry points
unconditionally reject before issuing a database query. Manually adding a
lookalike table to an `0098` database cannot enable loading. This keeps the Draft review executable only at
the offline-validation layer until a separate shared migration is approved.

Once that migration is approved and the required revision is updated, the
database receipt is inserted as the final statement in the same transaction.
The command then writes a new receipt file atomically after the transaction commits.
It refuses to overwrite or follow an existing receipt path. The receipt binds
the database/server identity, dataset, tenant, revision, manifest hash, loader
role and actual nonzero row counts. Store it for an independent review before a
binding is created in the primary database.

Example shape (do not run without the separate database approval):

```powershell
python scripts/load_seo_demo_fixture.py D:\approved\seo-tiger-v1 `
  --database-url-env SEO_FIXTURE_DATABASE_URL `
  --allow-host demo-db.internal `
  --allow-server-address 192.0.2.10 `
  --receipt D:\approved\receipts\seo-tiger-v1.json
```

Credentials belong only in the process environment. They must not appear in a
bundle, receipt, command transcript, repository file, or client request.
