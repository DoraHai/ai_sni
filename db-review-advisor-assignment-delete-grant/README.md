# SEO advisor assignment DELETE privilege supplement

This package records the one production privilege change approved on 2026-10-16. It supplements the historical `db-review-advisor-account-links` package, whose checksummed 0108 migration artifacts remain unchanged.

## Exact change

Run [`grant.sql`](grant.sql) as `sem_app`, the owner of `public.seo_site_advisor_assignments`:

```sql
GRANT DELETE ON public.seo_site_advisor_assignments TO sem_runtime;
```

Before this grant, `sem_runtime` had `SELECT` and `INSERT` on the target table. The SEO advisor assignment DELETE endpoint also needs table `DELETE`. It requires no sequence permission. The table has no user-defined triggers or inbound foreign keys; its four outbound foreign keys and their referential actions do not require another grant for deletion of an assignment row.

The production privilege matrix was captured immediately before and after execution using `information_schema.role_table_grants`, `information_schema.role_column_grants`, sequence privilege checks, and `pg_default_acl`. The only added row was `TABLE|public|seo_site_advisor_assignments|DELETE|sem_app|NO`; no row was removed. No migration or default privilege change is part of this supplement.

The snapshot files are retained in the deployment evidence, outside this repository, because they describe the live database rather than a schema migration.
