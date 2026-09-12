"""Create the shared immutable demo fixture receipt registry.

The registry is loader-owned and shared by SEM, SEO, and GEO.  Privileges and
fixture loading remain separate reviewed operations.  This migration accepts
only an absent ``demo_control`` schema so partial/manual objects cannot be
silently adopted.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0099_demo_fixture_registry"
down_revision = "0098_demo_binding_no_truncate"
branch_labels = None
depends_on = None


_SCHEMA_SQL = sa.text("""
SELECT n.nspname
FROM pg_catalog.pg_namespace AS n
WHERE n.nspname = 'demo_control'
""")


def upgrade() -> None:
    context = op.get_context()
    if context.as_sql:
        raise RuntimeError(
            "0099_demo_fixture_registry requires an online PostgreSQL catalog check"
        )

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("0099_demo_fixture_registry supports PostgreSQL only")

    bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    if bind.execute(_SCHEMA_SQL).first() is not None:
        raise RuntimeError(
            "refusing demo fixture registry adoption: demo_control schema already exists"
        )

    op.execute("CREATE SCHEMA demo_control")
    op.execute("""
        CREATE FUNCTION demo_control.is_nonnegative_integer_object(value jsonb)
        RETURNS boolean
        LANGUAGE sql
        IMMUTABLE STRICT PARALLEL SAFE
        AS $$
            SELECT jsonb_typeof(value) = 'object'
               AND value <> '{}'::jsonb
               AND NOT EXISTS (
                   SELECT 1
                   FROM jsonb_each(value) AS entry
                   WHERE jsonb_typeof(entry.value) <> 'number'
                      OR entry.value::text !~ '^(0|[1-9][0-9]*)$'
               )
        $$
    """)
    op.create_table(
        "fixture_registry",
        sa.Column("module_code", sa.String(length=3), nullable=False),
        sa.Column("demo_tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("dataset_key", sa.String(length=64), nullable=False),
        sa.Column("dataset_version", sa.String(length=40), nullable=False),
        sa.Column("fixture_namespace", sa.String(length=128), nullable=False),
        sa.Column("manifest_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("schema_revision", sa.String(length=64), nullable=False),
        sa.Column("loader_name", sa.String(length=80), nullable=False),
        sa.Column("loader_version", sa.String(length=80), nullable=False),
        sa.Column("row_counts", JSONB(), nullable=False),
        sa.Column("source_summary", JSONB(), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint(
            "module_code", "demo_tenant_id", "dataset_key", "dataset_version",
            name="pk_demo_fixture_registry",
        ),
        sa.CheckConstraint(
            "module_code IN ('sem','seo','geo')",
            name="ck_demo_fixture_registry_module",
        ),
        sa.CheckConstraint(
            "demo_tenant_id > 0",
            name="ck_demo_fixture_registry_tenant_positive",
        ),
        sa.CheckConstraint(
            "dataset_key ~ '^[a-z0-9][a-z0-9_-]{0,63}$'",
            name="ck_demo_fixture_registry_dataset_key_format",
        ),
        sa.CheckConstraint(
            "dataset_version ~ '^[a-z0-9][a-z0-9._-]{0,39}$'",
            name="ck_demo_fixture_registry_dataset_version_format",
        ),
        sa.CheckConstraint(
            "btrim(fixture_namespace) <> ''",
            name="ck_demo_fixture_registry_namespace_nonempty",
        ),
        sa.CheckConstraint(
            "manifest_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_demo_fixture_registry_manifest_sha256",
        ),
        sa.CheckConstraint(
            "schema_revision = '0099_demo_fixture_registry'",
            name="ck_demo_fixture_registry_schema_revision",
        ),
        sa.CheckConstraint(
            "btrim(loader_name) <> ''",
            name="ck_demo_fixture_registry_loader_name_nonempty",
        ),
        sa.CheckConstraint(
            "btrim(loader_version) <> ''",
            name="ck_demo_fixture_registry_loader_version_nonempty",
        ),
        sa.CheckConstraint(
            "demo_control.is_nonnegative_integer_object(row_counts)",
            name="ck_demo_fixture_registry_row_counts",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_summary) = 'object'",
            name="ck_demo_fixture_registry_source_summary",
        ),
        sa.CheckConstraint(
            "status = 'sealed'",
            name="ck_demo_fixture_registry_status",
        ),
        schema="demo_control",
    )
    op.execute("""
        CREATE FUNCTION demo_control.reject_fixture_registry_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'demo_control.fixture_registry is immutable';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_fixture_registry_no_update
        BEFORE UPDATE ON demo_control.fixture_registry
        FOR EACH ROW EXECUTE FUNCTION demo_control.reject_fixture_registry_mutation()
    """)
    op.execute("""
        CREATE TRIGGER trg_fixture_registry_no_delete
        BEFORE DELETE ON demo_control.fixture_registry
        FOR EACH ROW EXECUTE FUNCTION demo_control.reject_fixture_registry_mutation()
    """)
    op.execute("""
        CREATE TRIGGER trg_fixture_registry_no_truncate
        BEFORE TRUNCATE ON demo_control.fixture_registry
        FOR EACH STATEMENT EXECUTE FUNCTION demo_control.reject_fixture_registry_mutation()
    """)


def downgrade() -> None:
    raise RuntimeError(
        "0099_demo_fixture_registry is irreversible: retain sealed fixture receipts"
    )
