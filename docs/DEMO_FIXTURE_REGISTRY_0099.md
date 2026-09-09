# Shared demo fixture receipt contract (0099)

Status: code and isolated-test candidate only. This change does not authorize a
database connection, migration, fixture load, binding write, merge, or deploy.

`0099_demo_fixture_registry` creates one cross-module receipt table:
`demo_control.fixture_registry`. SEM, SEO, and GEO must use this table and must
not create module-specific receipt tables. Its composite identity is
`(module_code, demo_tenant_id, dataset_key, dataset_version)`. A sealed row also
records the fixture namespace, exact manifest SHA-256, schema revision, loader
identity and version, nonnegative per-table row counts, a source summary, and
the seal time. The revision accepts only `sem`, `seo`, and `geo`; it contains no
environment-specific role names and grants no privileges.

The table has no sequence. Separate `BEFORE UPDATE`, `BEFORE DELETE`, and
`BEFORE TRUNCATE` triggers call the reviewed rejection function, so a committed
receipt cannot be changed or removed. The migration is PostgreSQL-online-only,
checks the catalog before any DDL, rejects a pre-existing `demo_control` schema
or partial object, and refuses downgrade before DDL.

## Database and role boundaries

- `sem_prod` must keep `demo_control.fixture_registry` empty. No fixture rows or
  sealed receipts belong in the production database.
- Fixture rows and receipts are written only in `gsnipers_demo`. The loader
  role receives only the separately reviewed privileges needed to insert
  fixtures and `INSERT` the receipt. It must not receive DDL privileges.
- Each module runtime application role may receive `SELECT` on the shared
  registry so it can verify an exact sealed receipt. Runtime roles must not
  insert, update, delete, or truncate receipts.
- The migrator owns DDL. Privilege grants are an independent administrative
  action and are intentionally absent from the migration.
- Migrator, loader, and runtime roles are scoped to their intended database.
  None may cross from `gsnipers_demo` into `sem_prod`, or in the opposite
  direction, using inherited membership or database/schema grants.

## Load and binding order

The loader writes all fixture rows and the matching receipt in one reviewed
transaction, with the receipt last. A binding may be created only after that
transaction commits. The binding workflow must verify one exact `status =
'sealed'` receipt matching module, demo tenant, dataset key, dataset version,
manifest, namespace, and `schema_revision = '0099_demo_fixture_registry'`.
Missing, duplicated, malformed, or mismatched receipts fail closed.

The application rollout remains code-first compatible with both `0098` and
`0099`: SEO health accepts the reviewed `0098` shape without requiring future
objects, while `0099` additionally verifies the exact registry columns,
nullability, lack of defaults, named constraints, all three distinct triggers,
and both function definitions. This migration does not implement a fixture
loader, runtime data-source adapter, or module business behavior.
