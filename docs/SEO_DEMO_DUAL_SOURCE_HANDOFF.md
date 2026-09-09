# SEO same-site demo data source handoff

Status: development and offline tests only. No real demo database was connected,
no fixture was loaded, and no merge, deployment or migration is authorized by
this change.

The SEO service continues to authenticate every request against the primary
database. It then reads `public.demo_tenant_bindings` from that same primary
session. Exactly one active control record may map the authenticated production
tenant to an isolated demo tenant. Disabled, duplicate, malformed or unreadable
bindings fail closed. A tenant without a binding keeps the primary data source.
API-key superadmins cannot select the demo source.

The binding fixes the production tenant, demo tenant, dataset key, dataset
version and binding version. Query parameters and headers named `dataset`,
`data_source` or `database` are rejected. Clients continue to send and receive
the authenticated production tenant id; the isolated demo tenant id remains a
server-only mapping and is never required or exposed. Ordinary SEO tenant
scoping verifies any requested site. The
application checks `current_database()`, `inet_server_addr()`, exactly one
Alembic revision (`0098_demo_binding_no_truncate`), and every bound tenant site's
dataset key, dataset version and three stored safety flags before yielding a demo
session. At least one matching site must exist. The transaction is set to `READ
ONLY` and rolled back when the request ends.

Demo identities may use GET, HEAD and OPTIONS only. OAuth paths are rejected for
all methods. Schedulers retain the primary session factory and never receive the
demo database factory, so the demo tenant cannot be collected, generated or
published by a scheduled job. The HTTP method gate rejects manual collection,
generation, publication, OAuth and every other write before a demo business
session is opened.

Required server-owned settings (values deliberately omitted):

- `SEO_DEMO_DATA_SOURCE_ENABLED`
- `SEO_DEMO_DATABASE_URL`
- `SEO_DEMO_DATABASE_HOST_ALLOWLIST`
- `SEO_DEMO_DATABASE_SERVER_ADDR_ALLOWLIST`
- `SEO_DEMO_DATABASE_NAME`

The trusted binding contract is migration-owned and contains `tenant_id`,
`demo_tenant_id`, `dataset_key`, `dataset_version`, status and audit metadata.
It contains no connection details. Credentials must remain in deployment
secrets and must not appear in a client request, log, document or repository
file.

For the proposed Tiger dataset, fixture preparation must stamp every `seo_sites`
row for its demo tenant with the reviewed `dataset_key` and `dataset_version`,
plus `synthetic=true`, `scheduler_excluded=true` and
`external_actions_disabled=true`. Fixture loading, binding creation, migration
and connection to either database remain separate reviewed operations; this PR
does not perform them.

## Schema baseline

The demo target and primary control plane must each report exactly
`0098_demo_binding_no_truncate`. Earlier compatible production rollout versions
are deliberately rejected for demo routing because they do not contain the full
binding control plane and truncate protection. This implementation does not
authorize merging, deployment, binding writes, fixture loading or migration.
