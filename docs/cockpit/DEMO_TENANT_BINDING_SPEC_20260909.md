# Demo tenant binding contract

Status: coordinator draft for cross-module review. This document authorizes no database, migration, seed, merge or deployment action.

## Purpose

`demo_tenant_bindings` is the only production control-plane record that may route an authenticated tenant to the isolated demo database. It maps a production tenant identity to a demo dataset and the non-authoritative tenant anchor inside `gsnipers_demo`. It never stores a database URL, credential, engine name, host, schema or arbitrary client routing input.

The server must authenticate the user, resolve the effective production tenant and verify module entitlement before reading this table. A request body, query parameter, header, local storage value or ordinary `tenant_id` cannot activate demo routing by itself.

## Proposed 0097 table

| Column | Type | Null | Rule |
| --- | --- | --- | --- |
| `tenant_id` | `BIGINT` | no | Primary key; named FK to `public.tenants(id)` with `ON DELETE RESTRICT` |
| `demo_tenant_id` | `BIGINT` | no | Unique logical FK anchor in `gsnipers_demo`; no cross-database FK |
| `dataset_key` | `VARCHAR(64)` | no | Unique stable key; lower-case ASCII letters, digits, `_` and `-` only |
| `dataset_version` | `VARCHAR(40)` | no | Immutable fixture release identifier used in evidence and cache keys |
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
- checks for status, positive version, dataset-key format and status/disabled-at consistency

No index beyond the primary key and two unique indexes is proposed until an observed query requires it.

## Resolver contract

1. Resolve the effective production tenant through existing authenticated scope rules.
2. Verify the requested module is entitled and unexpired for that tenant.
3. Read exactly one binding by production `tenant_id` from the production control database.
4. Require `status=active`, a recognized `dataset_key` and an allowlisted `dataset_version`.
5. Select the preconfigured demo session factory. The binding can select only dataset identity, never connection configuration.
6. Inside the demo read-only transaction, require the structural shadow tenant to match `demo_tenant_id` and the fixture registry to match both dataset fields.
7. On missing, duplicate, disabled, unknown, stale or unreachable state, fail closed. Never retry against production business tables.

Cache keys and observability records must include production tenant ID, demo tenant ID, dataset key, dataset version, module and requested period. Logs must not include credentials or customer payloads.

## Shadow identity boundary

`gsnipers_demo` may contain minimal `tenants/users/roles/tenant_modules` rows only as foreign-key anchors required by the shared schema and fixtures. They are not authentication or authorization authorities. Password hashes and production tokens must not be copied. The production Auth service remains authoritative, and every demo request must carry the already verified production identity context.

The fixture loader must assert that every module row belongs to the bound `demo_tenant_id`, and that no additional active tenant exists in the demo dataset unless explicitly approved for another binding.

## Mutation and administration

The first release has no customer-facing mutation endpoint. Binding creation, disablement and version rollover require a separately reviewed super-admin API or controlled database package with optimistic locking and an audit trail. Deleting bindings is prohibited; disable them instead. Changing `tenant_id`, `demo_tenant_id` or `dataset_key` in place is prohibited; disable the old binding and create a reviewed replacement.

Module APIs may expose non-sensitive `workspace_mode=demo`, `data_label=全虚拟演示数据` and `dataset_version` after the resolver succeeds. They must not expose `demo_tenant_id`, connection details or binding audit fields to ordinary users.

## Required tests

- bound user, authorized super-admin and cross-tenant denial
- forged tenant, header, query and storage values cannot select demo data
- missing, duplicate, disabled, unknown-version and unavailable-demo-database failures do not fall back
- production and demo session factories cannot be interchanged by request input
- cache isolation across production tenant, demo tenant, module, version and period
- shadow identity is never accepted for login or authorization
- optimistic-lock conflict, disabled-at consistency and immutable-key enforcement
- scheduler, worker, OAuth, collection, model, writeback and publication paths reject the demo tenant
- production tenants preserve existing behavior and never query the demo database
- catalog assertions for all named constraints, types, defaults and indexes

## Open review points

- Confirm whether `dataset_version` should accept a 40-character git SHA only or a stable fixture release token.
- Confirm whether super-admins may enter every active demo binding or require an additional permission.
- Decide the controlled API and audit-history design for future binding changes; it is outside the initial migration.
- Confirm the exact structural shadow rows required by all three module fixture loaders after the unified empty-database migration rehearsal.
