# SEO same-site demo data source handoff

Status: development and offline tests only. No real demo database was connected,
no fixture was loaded, and no merge, deployment or migration is authorized by
this change.

The SEO service continues to authenticate every request against the primary
database. A dedicated production user can reach the isolated demo database only
when its user id is present in `SEO_DEMO_PRINCIPAL_USER_IDS` and exactly one
enabled record in `SEO_DEMO_BINDINGS_JSON` matches both its authenticated user
id and authenticated tenant id. Missing, duplicate, disabled or malformed
bindings fail closed. API-key superadmins cannot select the demo source.

The binding fixes the target tenant, permitted site ids, fixture marker and
Alembic revision. Query parameters and headers named `dataset`, `data_source` or
`database` are rejected; tenant and site parameters can only match the bound
values. The application checks `current_database()`, `inet_server_addr()`, exactly one Alembic
revision, the fixture marker and all three stored safety flags before yielding a
demo session. The transaction is set to `READ ONLY` and rolled back when the
request ends.

Demo identities may use GET, HEAD and OPTIONS only. OAuth paths are rejected for
all methods. Schedulers retain the primary session factory and never receive the
demo database factory, so the demo tenant cannot be collected, generated or
published by a scheduled job. The HTTP method gate rejects manual collection,
generation, publication, OAuth and every other write before a demo business
session is opened.

Required server-owned settings (values deliberately omitted):

- `SEO_DEMO_DATA_SOURCE_ENABLED`
- `SEO_DEMO_PRINCIPAL_USER_IDS`
- `SEO_DEMO_BINDINGS_JSON`
- `SEO_DEMO_DATABASE_URL`
- `SEO_DEMO_DATABASE_HOST_ALLOWLIST`
- `SEO_DEMO_DATABASE_SERVER_ADDR_ALLOWLIST`
- `SEO_DEMO_DATABASE_NAME`

The binding JSON contract is an exact list of objects with
`principal_user_id`, `principal_tenant_id`, `tenant_id`, `site_ids`,
`dataset_key`, `schema_revision` and `enabled`. Extra fields are rejected.
Credentials must remain in deployment secrets and must not appear in a client
request, log, document or repository file.

## Migration review record retained for coordination

The final read-only review of exact commit
`d23b2d8065cd81d2c7d29266d5f1c82771857fd6` reported P1=0 and P2=0. Local
focused tests reported 86 passed and 5 PostgreSQL-dependent skips; the exact
commit's PostgreSQL 16 migration-validation job passed. That review does not
authorize merging, deploying or executing migration `0095_adopt_geo_ticket`.
