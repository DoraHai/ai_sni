# Canonical migration 0095: adopt GEO ticket assignment columns

Status: implementation candidate only. It has not been merged, deployed, or run
against any shared database.

## Purpose

The production database is stamped at `0094_seo_qa_batches`, but
`public.geo_action_tickets` already contains the two columns formerly introduced
on the separate GEO code-tree tip `0074_geo_ticket_assignment`:

- `owner_name character varying(100) NULL`
- `due_date date NULL`

The canonical migration chain must preserve that production shape while also
being able to create an empty demo database. Revision
`0095_adopt_geo_ticket`, whose only parent is `0094_seo_qa_batches`, performs
that adoption.

## Accepted starting states

The migration takes an `ACCESS EXCLUSIVE` table lock before catalog inspection
and accepts exactly two states:

1. Both reviewed columns already exist with the exact reviewed PostgreSQL
   types, nullability, defaults, identity/generated/domain/collation behavior,
   and no referencing indexes or constraints. The revision performs no DDL and
   only advances the Alembic version.
2. Both columns are absent. The revision creates both nullable columns and
   revalidates the resulting catalog shape in the same transaction.

A missing table, a partial pair, type/default/nullability drift, a domain,
non-default collation behavior, an identity/generated expression, or a
referencing index/constraint stops the migration. There is no automatic repair.

Offline SQL generation and non-PostgreSQL execution are rejected because the
decision depends on the live catalog. Downgrade is deliberately irreversible:
the adopted columns may already contain production audit data.

## Rollout boundary

The SEO runtime recognizes both `0094_seo_qa_batches` and
`0095_adopt_geo_ticket` during a controlled rollout. The ordinary SEO deploy
workflow still records `migration=not-run`; schema execution must remain a
separate reviewed operation.

Before any shared-database execution, the exact candidate commit still requires:

- an independent SEM, SEO, and GEO boundary review;
- an online PostgreSQL 16 rehearsal from a fresh canonical database;
- an online PostgreSQL 16 rehearsal of the exact reviewed 0094 production
  catalog shape, confirming the no-DDL adoption path preserves values;
- a reviewed execution and rollback-by-forward-plan. No `stamp` is permitted.

Only after 0095 is accepted may the separately reviewed `sem_tasks` migration
be assigned revision 0096. The trusted demo binding tables remain revision 0097.
