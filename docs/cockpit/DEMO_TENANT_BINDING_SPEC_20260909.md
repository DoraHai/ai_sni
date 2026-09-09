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
- checks for positive demo tenant ID, positive version, non-empty dataset key/version formats, status, status/disabled-at consistency, `disabled_at >= bound_at`, and `updated_by_user_id` being present when disabled

No index beyond the primary key and two unique indexes is proposed until an observed query requires it.

## Resolver contract

1. Resolve the effective production tenant through existing authenticated scope rules. An unbound administrator must provide exactly one valid production tenant context; missing, malformed or conflicting tenant candidates fail.
2. Verify the requested module is entitled and unexpired for that tenant using the production control session. Calendar boundaries use `Asia/Shanghai` explicitly.
3. Build an immutable access context, then read exactly one binding by production `tenant_id` from the production control database. Shadow rows and demo sessions never participate in authentication or entitlement checks.
4. Require `status=active`, a recognized `dataset_key` and an allowlisted `dataset_version`.
5. Select the preconfigured demo session factory. The binding can select only dataset identity, never connection configuration.
6. Inside the demo read-only transaction, verify `transaction_read_only=on`, require the structural shadow tenant to match `demo_tenant_id` and the fixture registry to match both dataset fields.
7. On missing, duplicate, disabled, unknown, stale or unreachable state, fail closed. Never retry against production business tables.

Cache keys and observability records must include production tenant ID, demo tenant ID, dataset key, dataset version, module and requested period. Logs must not include credentials or customer payloads.

## Shadow identity boundary

`gsnipers_demo` may contain minimal `tenants/users/roles/tenant_modules` rows only as foreign-key anchors required by the shared schema and fixtures. They are not authentication or authorization authorities. Password hashes and production tokens must not be copied. The production Auth service remains authoritative, and every demo request must carry the already verified production identity context.

The fixture loader must assert that every module row belongs to the bound `demo_tenant_id`, and that no additional active tenant exists in the demo dataset unless explicitly approved for another binding.

## Mutation and administration

The first release has no customer-facing mutation endpoint. Application runtime roles receive `SELECT` only on this table. Binding creation and disablement require a controlled database package executed by a separately authorized role with an audit trail. Deleting bindings is prohibited; disable them instead. Reactivation is prohibited in the first release. Changing `tenant_id`, `demo_tenant_id`, `dataset_key` or `dataset_version` in place is prohibited; disable the old binding and create a reviewed replacement after the new registry has been fully loaded and verified.

Module APIs may expose non-sensitive `workspace_mode=demo`, `data_label=全虚拟演示数据` and `dataset_version` after the resolver succeeds. They must not expose `demo_tenant_id`, `dataset_key`, connection details or binding audit fields to ordinary users.

Schedulers, recovery jobs, asynchronous claims, direct executors, OAuth callbacks, generation, publication and push workers must re-check the production binding after claiming work and before any model, network or write action. Queue-time checks and missing external configuration are insufficient. Demo tenants cannot create public share tokens.

GEO formal metrics and completion evidence must accept the immutable access context and force all official values and trends to `null` with a `demo_tenant` exclusion reason before sample eligibility is evaluated. This remains true if fixture rows are altered to look like real samples. Demo summaries use a separate explicitly non-official contract.

## Required tests

- bound user, authorized super-admin and cross-tenant denial
- forged tenant, header, query and storage values cannot select demo data
- missing, duplicate, disabled, unknown-version and unavailable-demo-database failures do not fall back
- production and demo session factories cannot be interchanged by request input
- cache isolation across production tenant, demo tenant, module, version and period
- shadow identity is never accepted for login or authorization
- optimistic-lock conflict, disabled-at consistency and immutable-key enforcement
- scheduler, worker, recovery, direct executor, OAuth callback, collection, model, writeback, public share and publication paths reject the demo tenant, including a queue-time-to-claim-time binding race
- production tenants preserve existing behavior and never query the demo database
- catalog assertions for all named constraints, types, defaults and indexes

## Open review points

- Confirm that all three fixture manifests and the demo registry use the same stable release token format and value.
- Confirm whether super-admins may enter every active demo binding or require an additional permission.
- Decide the controlled API and audit-history design for future binding changes; it is outside the initial migration.
- Confirm the exact structural shadow rows required by all three module fixture loaders after the unified empty-database migration rehearsal.
