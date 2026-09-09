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

## Revision 0098 execution gate

Revision `0098_demo_binding_no_truncate` has no approved fixture registry.
Therefore the transaction, command, and receipt-recovery entry points all raise
an error before opening a connection, issuing a catalog query, or writing data.
Adding an ad hoc table or function cannot enable them. This module contains no
alternate/private execution path.

The only future integration marker is the inert `REGISTRY_CONTRACT` value. It
names the shared `demo_control.fixture_registry` object and records that its
`0099` contract is still pending. After the shared migration is merged, this
branch must rebase and consume the reviewed health and registry API. SEO will
not define its own registry table, trigger, refusal function, permission model,
or migration.

Until that rebase, the supported operation is offline bundle validation only.
No database, fixture load, binding, merge, or deployment is authorized.

Credentials belong only in the process environment. They must not appear in a
bundle, receipt, command transcript, repository file, or client request.
