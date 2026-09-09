# SEO demo fixture receipt migration proposal

Status: design only. No revision is assigned and this file is not an Alembic
migration. The current `0098_demo_binding_no_truncate` database does not contain
this registry, so the loader deliberately fails before its first data insert.

The next shared migration review may adopt the following object after assigning
an approved revision and parent:

```sql
CREATE TABLE seo_fixture_load_receipts (
    manifest_sha256 char(64) PRIMARY KEY,
    dataset_key varchar(64) NOT NULL UNIQUE,
    dataset_version varchar(40) NOT NULL,
    demo_tenant_id bigint NOT NULL,
    target_revision varchar(64) NOT NULL,
    target_database varchar(64) NOT NULL,
    server_address inet NOT NULL,
    loader_role name NOT NULL,
    loader_version varchar(80) NOT NULL,
    row_counts jsonb NOT NULL,
    committed_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_seo_fixture_receipt_hash
      CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$')
);
```

The reviewed migration must create
`public.reject_seo_fixture_receipt_mutation()` and add separate `BEFORE UPDATE`,
`BEFORE DELETE`, and `BEFORE TRUNCATE` triggers on exactly
`public.seo_fixture_load_receipts`; every trigger must call that function and it
must always raise an exception. The loader role gets
only `SELECT, INSERT`; the application read role gets no access. No sequence is
used. The loader inserts the receipt as the final statement of the same
SERIALIZABLE transaction as the fixture rows, so a committed registry row is
the durable source of truth if writing the local JSON copy later fails.

After that migration is approved, the loader's required revision and registry
schema tests must be updated in the same review. Until then no database is a
valid load target, even when its Alembic head is exactly `0098`.
