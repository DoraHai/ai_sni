# Demo tenant binding contract

Status: coordinator draft for cross-module review. This document authorizes no database, migration, seed, merge or deployment action.

## Purpose

`demo_tenant_bindings` is the only production control-plane record that may route an authenticated tenant to the isolated demo database. It maps a production tenant identity to a demo dataset and the non-authoritative tenant anchor inside `gsnipers_demo`. It never stores a database URL, credential, engine name, host, schema or arbitrary client routing input.

The server must authenticate the user, resolve the effective production tenant and verify module entitlement before reading this table. A request body, query parameter, header, local storage value or ordinary `tenant_id` cannot activate demo routing by itself.

## Proposed 0097 table

| Column | Type | Null | Rule |
| --- | --- | --- | --- |
| `tenant_id` | `BIGINT` | no | Primary key; named FK to `public.tenants(id)` with `ON DELETE RESTRICT` |
| `demo_tenant_id` | `BIGINT` | no | Positive, unique logical FK anchor in `gsnipers_demo`; no cross-database FK |
| `dataset_key` | `VARCHAR(64)` | no | Unique stable key; lower-case ASCII letters, digits, `_` and `-` only |
| `dataset_version` | `VARCHAR(40)` | no | Immutable stable fixture release token such as `demo-20260909-v1`; lower-case ASCII letters, digits, `.`, `_` and `-` only |
| `status` | `VARCHAR(16)` | no | `active` or `disabled`; no implicit default |
| `bound_by_user_id` | `BIGINT` | no | Named FK to `public.users(id)` with `ON DELETE RESTRICT` |
| `bound_at` | `TIMESTAMPTZ` | no | Server default `now()` |
| `updated_by_user_id` | `BIGINT` | yes | Named FK to `public.users(id)` with `ON DELETE RESTRICT` |
| `updated_at` | `TIMESTAMPTZ` | no | Server default `now()`; application updates explicitly |
| `disabled_at` | `TIMESTAMPTZ` | yes | Must be null while active and non-null while disabled |
| `version` | `INTEGER` | no | Server default `1`; positive optimistic-lock value |
| `notes` | `VARCHAR(500)` | yes | Administrative explanation only; never interpreted as routing data |

Proposed constraints:

- primary key `pk_demo_tenant_bindings`
- foreign keys `fk_demo_tenant_bindings_tenant`, `fk_demo_tenant_bindings_bound_by`, `fk_demo_tenant_bindings_updated_by`
- unique constraints `uq_demo_tenant_bindings_demo_tenant` and `uq_demo_tenant_bindings_dataset_key`
- checks for positive demo tenant ID, positive version, non-empty dataset key/version formats, status, status/disabled-at consistency, `updated_at >= bound_at`, `disabled_at >= bound_at`, and `updated_by_user_id` being present when disabled

No index beyond the primary key and two unique indexes is proposed until an observed query requires it.

`dataset_key` uses `^[a-z0-9][a-z0-9_-]{0,63}$`. `dataset_version` uses the stable release-token form `^[a-z0-9][a-z0-9._-]{0,39}$`; git SHAs are not a separate accepted format. Comparisons use the complete normalized value, never a prefix.

## Proposed append-only history

Because the main table represents the current binding, controlled replacement is allowed only with a mandatory append-only `demo_tenant_binding_history` record in the same transaction. The history row records its own BIGINT primary key, production tenant ID, binding version, operation (`create`, `disable`, `replace`), complete before/after binding snapshots as JSON objects, actor user ID, non-empty reason and timestamp. Runtime roles receive no mutation permission on either table. The controlled role may insert history and insert/update the current table but may not update/delete history or delete a current binding.

## Resolver contract

1. Resolve the effective production tenant through existing authenticated scope rules. An unbound administrator must provide exactly one valid production tenant context; missing, malformed or conflicting tenant candidates fail.
2. Verify the requested module is entitled and unexpired for that tenant using the production control session. Calendar boundaries use `Asia/Shanghai` explicitly.
3. Build an immutable `ModuleDataScope`, then read exactly one binding by production `tenant_id` from the production control database. Shadow rows and demo sessions never participate in authentication or entitlement checks. The control session and selected data session use distinct types/interfaces so handlers cannot interchange them.
4. Require `status=active`, a recognized `dataset_key` and an allowlisted `dataset_version`.
5. Select the preconfigured demo session factory. The binding can select only dataset identity, never connection configuration.
6. Inside the demo read-only transaction, verify `transaction_read_only=on`, require the structural shadow tenant to match `demo_tenant_id` and the fixture registry to match both dataset fields.
7. On missing, duplicate, disabled, unknown, stale or unreachable state, fail closed. Never retry against production business tables.

Binding resolution precedes every data or response cache lookup. Cache keys and observability records must include production tenant ID, demo tenant ID, dataset key, dataset version, binding version, module, endpoint/response-schema version, normalized account/object filters, requested and actual period, paging/sort inputs, units and permission projection. Disabling or replacing a binding makes every prior key unreachable. Logs must not include credentials or customer payloads.

## Shadow identity boundary

`gsnipers_demo` may contain minimal `tenants/users/roles/tenant_modules` rows only as foreign-key anchors required by the shared schema and fixtures. They are not authentication or authorization authorities. Password hashes and production tokens must not be copied. The production Auth service remains authoritative, and every demo request must carry the already verified production identity context.

The fixture loader must assert that every module row belongs to the bound `demo_tenant_id`, and that no additional active tenant exists in the demo dataset unless explicitly approved for another binding.

## Demo fixture registry

The demo database has a separately reviewed `demo_control` schema owned by the fixture loader, not by production Alembic migrations. Its registry records `dataset_key`, stable `dataset_version`, manifest SHA-256, unified business-schema revision, positive demo tenant ID, load status and load/verification timestamps. A ready dataset has exactly one matching registry row. The demo application role receives SELECT only; the loader may replace registry and fixture contents atomically.

An optional append-only object registry records module, object type, stable fixture object key and database object ID under the same dataset and demo tenant. This supports stable links and evidence without treating equal numeric IDs across databases as the same object.

The dedicated presentation tenant has no synthetic production business site. For SEO, after the production binding selects the demo data session, the service enumerates sites from that session under `demo_tenant_id`. A client `site_id` is only a candidate and must resolve with `WHERE tenant_id=:demo_tenant_id AND id=:site_id`; it cannot select a database. The resolved demo site identity or stable registry key is included in cache keys. A production-site-to-demo-site mapping is neither required nor allowed for this dedicated tenant.

## Mutation and administration

The first release has no customer-facing mutation endpoint. Application runtime roles receive `SELECT` only on the current and history tables. Binding create, disable and replacement require a controlled database package executed by a separately authorized role. Delete is prohibited. A replacement first loads and verifies the new registry, then uses `WHERE tenant_id=:tenant_id AND version=:old_version`, appends the complete before/after history, updates the current mapping/status/audit fields and increments `version` atomically. Every change sets `updated_by_user_id` and `updated_at`; initial creation sets the updater equal to the binder. Ordinary reactivation without a reviewed replacement is prohibited.

Module APIs may expose non-sensitive `workspace_mode=demo`, `data_label=全虚拟演示数据` and `dataset_version` after the resolver succeeds. They must not expose `demo_tenant_id`, `dataset_key`, connection details or binding audit fields to ordinary users.

Schedulers, recovery jobs, asynchronous claims, direct executors, OAuth callbacks, generation, publication and push workers must re-check the production binding after claiming work and before any model, network or write action. Queue-time checks and missing external configuration are insufficient. Demo tenants cannot create public share tokens.

In a production process, demo safety is tenant-scoped and cannot depend on process-wide `APP_ENV=demo`. Mutating HTTP routes reject an active demo binding before loading business objects. Scheduler enumeration excludes active bindings and every sync, collection, OAuth, external client, AI generation, cache-generation, state-update and writeback entry point re-checks before transport or mutation.

GEO formal metrics and completion evidence must accept the immutable access context and force all official values and trends to `null` with a `demo_tenant` exclusion reason before sample eligibility is evaluated. This remains true if fixture rows are altered to look like real samples. Demo summaries use a separate explicitly non-official contract.

## Required tests

- bound user, authorized super-admin and cross-tenant denial
- forged tenant, header, query and storage values cannot select demo data
- missing, duplicate, disabled, unknown-version and unavailable-demo-database failures do not fall back
- production control and selected data session types cannot be interchanged; SQL tracing proves identity/entitlement/binding use only the control engine and module repositories use only the selected data engine
- cache isolation across production tenant, demo tenant, module, version and period
- shadow identity is never accepted for login or authorization
- optimistic-lock conflict, disabled-at consistency, controlled replacement and atomic append-only before/after history
- scheduler, worker, recovery, direct executor, OAuth callback, collection, model, writeback, public share and publication paths reject the demo tenant, including a queue-time-to-claim-time binding race
- production tenants preserve existing behavior and never query the demo database
- catalog assertions for all named constraints, types, defaults and indexes

## Open review points

- Confirm that all three fixture manifests and the demo registry use the same stable release token format and value.
- Confirm whether super-admins may enter every active demo binding or require an additional permission.
- Decide the controlled API and audit-history design for future binding changes; it is outside the initial migration.
- Confirm the exact structural shadow rows and `demo_control` registry DDL required by all three module fixture loaders after the unified empty-database migration rehearsal.
