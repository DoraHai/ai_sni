"""Adopt the reviewed GEO ticket assignment columns into the canonical chain.

This revision is deliberately PostgreSQL- and online-only.  Production already
contains the two columns from the retired GEO-only migration branch, while a
fresh database built from the canonical chain does not.  The migration accepts
only those two exact states and fails closed for every partial or drifted shape.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0095_adopt_geo_ticket"
down_revision = "0094_seo_qa_batches"
branch_labels = None
depends_on = None


_SCHEMA = "public"
_TABLE = "geo_action_tickets"
_EXPECTED_COLUMNS = {
    "owner_name": {
        "formatted_type": "character varying(100)",
        "attnotnull": False,
        "default_expression": None,
        "attidentity": "",
        "attgenerated": "",
        "typtype": "b",
        "domain_base_type": None,
        "collation_is_type_default": True,
    },
    "due_date": {
        "formatted_type": "date",
        "attnotnull": False,
        "default_expression": None,
        "attidentity": "",
        "attgenerated": "",
        "typtype": "b",
        "domain_base_type": None,
        "collation_is_type_default": True,
    },
}


_TABLE_SQL = sa.text("""
SELECT c.relkind::text
FROM pg_catalog.pg_class AS c
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relname = 'geo_action_tickets'
""")

_COLUMN_SQL = sa.text("""
SELECT
    a.attname,
    pg_catalog.format_type(a.atttypid, a.atttypmod) AS formatted_type,
    a.attnotnull,
    pg_catalog.pg_get_expr(ad.adbin, ad.adrelid) AS default_expression,
    a.attidentity,
    a.attgenerated,
    t.typtype,
    CASE WHEN t.typbasetype = 0 THEN NULL ELSE bt.typname END AS domain_base_type,
    a.attcollation = t.typcollation AS collation_is_type_default
FROM pg_catalog.pg_attribute AS a
JOIN pg_catalog.pg_class AS c ON c.oid = a.attrelid
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
JOIN pg_catalog.pg_type AS t ON t.oid = a.atttypid
LEFT JOIN pg_catalog.pg_type AS bt ON bt.oid = t.typbasetype
LEFT JOIN pg_catalog.pg_attrdef AS ad
    ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
WHERE n.nspname = 'public'
  AND c.relname = 'geo_action_tickets'
  AND a.attname IN ('owner_name', 'due_date')
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY a.attname
""")

_INDEX_SQL = sa.text("""
SELECT DISTINCT index_class.relname AS object_name
FROM pg_catalog.pg_class AS table_class
JOIN pg_catalog.pg_namespace AS n ON n.oid = table_class.relnamespace
JOIN pg_catalog.pg_attribute AS a
  ON a.attrelid = table_class.oid
JOIN pg_catalog.pg_depend AS dep
  ON dep.refclassid = 'pg_catalog.pg_class'::pg_catalog.regclass
 AND dep.refobjid = table_class.oid
 AND dep.refobjsubid = a.attnum
JOIN pg_catalog.pg_class AS index_class
  ON dep.classid = 'pg_catalog.pg_class'::pg_catalog.regclass
 AND index_class.oid = dep.objid
JOIN pg_catalog.pg_index AS i
  ON i.indexrelid = index_class.oid AND i.indrelid = table_class.oid
WHERE n.nspname = 'public'
  AND table_class.relname = 'geo_action_tickets'
  AND a.attname IN ('owner_name', 'due_date')
ORDER BY index_class.relname
""")

_CONSTRAINT_SQL = sa.text("""
SELECT DISTINCT con.conname AS object_name
FROM pg_catalog.pg_class AS table_class
JOIN pg_catalog.pg_namespace AS n ON n.oid = table_class.relnamespace
JOIN pg_catalog.pg_attribute AS a
  ON a.attrelid = table_class.oid
JOIN pg_catalog.pg_depend AS dep
  ON dep.refclassid = 'pg_catalog.pg_class'::pg_catalog.regclass
 AND dep.refobjid = table_class.oid
 AND dep.refobjsubid = a.attnum
JOIN pg_catalog.pg_constraint AS con
  ON dep.classid = 'pg_catalog.pg_constraint'::pg_catalog.regclass
 AND con.oid = dep.objid
WHERE n.nspname = 'public'
  AND table_class.relname = 'geo_action_tickets'
  AND a.attname IN ('owner_name', 'due_date')
ORDER BY con.conname
""")


def _catalog_state(bind) -> dict[str, dict[str, object]]:
    table_rows = bind.execute(_TABLE_SQL).all()
    if len(table_rows) != 1 or table_rows[0][0] != "r":
        raise RuntimeError("public.geo_action_tickets must exist as one ordinary table")

    rows = bind.execute(_COLUMN_SQL).mappings().all()
    return {str(row["attname"]): dict(row) for row in rows}


def _validate_exact(bind) -> None:
    actual = _catalog_state(bind)
    if set(actual) != set(_EXPECTED_COLUMNS):
        raise RuntimeError(
            "geo_action_tickets assignment columns are partial or missing after adoption: "
            f"found {sorted(actual)}"
        )

    for name, expected in _EXPECTED_COLUMNS.items():
        observed = {key: actual[name].get(key) for key in expected}
        if observed != expected:
            raise RuntimeError(
                f"public.geo_action_tickets.{name} does not match the reviewed production shape: "
                f"observed {observed!r}"
            )

    indexes = [row[0] for row in bind.execute(_INDEX_SQL).all()]
    constraints = [row[0] for row in bind.execute(_CONSTRAINT_SQL).all()]
    if indexes or constraints:
        raise RuntimeError(
            "reviewed assignment columns must not have indexes or constraints: "
            f"indexes={indexes!r}, constraints={constraints!r}"
        )


def upgrade() -> None:
    context = op.get_context()
    if context.as_sql:
        raise RuntimeError("0095_adopt_geo_ticket requires an online PostgreSQL catalog check")

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("0095_adopt_geo_ticket supports PostgreSQL only")

    # Keep the inspected shape stable until Alembic commits this migration,
    # without waiting indefinitely behind application traffic or another DDL.
    bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    bind.execute(sa.text("LOCK TABLE public.geo_action_tickets IN ACCESS EXCLUSIVE MODE"))
    current = _catalog_state(bind)
    present = set(current)

    if not present:
        op.add_column(
            _TABLE,
            sa.Column("owner_name", sa.String(length=100), nullable=True),
            schema=_SCHEMA,
        )
        op.add_column(
            _TABLE,
            sa.Column("due_date", sa.Date(), nullable=True),
            schema=_SCHEMA,
        )
    elif present != set(_EXPECTED_COLUMNS):
        raise RuntimeError(
            "refusing partial geo_action_tickets adoption: "
            f"found {sorted(present)}, expected both columns or neither"
        )

    _validate_exact(bind)


def downgrade() -> None:
    raise RuntimeError(
        "0095_adopt_geo_ticket is irreversible: the columns may contain production audit data"
    )
