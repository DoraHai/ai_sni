"""Create the trusted demo tenant binding control plane.

The current binding and append-only history live only in ``public``.  They
contain dataset identity, never connection details.  Grants and application
routing are deliberately outside this migration and require separate review.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0097_demo_tenant_bindings"
down_revision = "0096_sem_tasks"
branch_labels = None
depends_on = None

_SNAPSHOT_KEYS = (
    "tenant_id", "demo_tenant_id", "dataset_key", "dataset_version", "status",
    "bound_by_user_id", "bound_at", "updated_by_user_id", "updated_at",
    "disabled_at", "version", "notes",
)


def _snapshot_contract(column: str) -> str:
    keys = ",".join(f"'{key}'" for key in _SNAPSHOT_KEYS)
    required = ",".join(f"'{key}'" for key in _SNAPSHOT_KEYS)
    return (
        f"jsonb_typeof({column}) = 'object' "
        f"AND {column} ?& ARRAY[{required}]::text[] "
        f"AND ({column} - ARRAY[{keys}]::text[]) = '{{}}'::jsonb "
        f"AND jsonb_typeof({column}->'tenant_id') = 'number' "
        f"AND ({column}->>'tenant_id') ~ '^[1-9][0-9]*$' "
        f"AND jsonb_typeof({column}->'demo_tenant_id') = 'number' "
        f"AND ({column}->>'demo_tenant_id') ~ '^[1-9][0-9]*$' "
        f"AND jsonb_typeof({column}->'dataset_key') = 'string' "
        f"AND ({column}->>'dataset_key') ~ '^[a-z0-9][a-z0-9_-]{{0,63}}$' "
        f"AND jsonb_typeof({column}->'dataset_version') = 'string' "
        f"AND ({column}->>'dataset_version') ~ '^[a-z0-9][a-z0-9._-]{{0,39}}$' "
        f"AND jsonb_typeof({column}->'status') = 'string' "
        f"AND ({column}->>'status') IN ('active','disabled') "
        f"AND jsonb_typeof({column}->'bound_by_user_id') = 'number' "
        f"AND ({column}->>'bound_by_user_id') ~ '^[1-9][0-9]*$' "
        f"AND jsonb_typeof({column}->'updated_by_user_id') = 'number' "
        f"AND ({column}->>'updated_by_user_id') ~ '^[1-9][0-9]*$' "
        f"AND jsonb_typeof({column}->'version') = 'number' "
        f"AND ({column}->>'version') ~ '^[1-9][0-9]*$' "
        f"AND jsonb_typeof({column}->'bound_at') = 'string' "
        f"AND jsonb_typeof({column}->'updated_at') = 'string' "
        f"AND jsonb_typeof({column}->'disabled_at') IN ('null','string') "
        f"AND jsonb_typeof({column}->'notes') IN ('null','string')"
    )


def upgrade() -> None:
    op.create_table(
        "demo_tenant_bindings",
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("demo_tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("dataset_key", sa.String(length=64), nullable=False),
        sa.Column("dataset_version", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("bound_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("bound_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", name="pk_demo_tenant_bindings"),
        sa.ForeignKeyConstraint(["tenant_id"], ["public.tenants.id"], name="fk_demo_tenant_bindings_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["bound_by_user_id"], ["public.users.id"], name="fk_demo_tenant_bindings_bound_by", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["public.users.id"], name="fk_demo_tenant_bindings_updated_by", ondelete="RESTRICT"),
        sa.UniqueConstraint("demo_tenant_id", name="uq_demo_tenant_bindings_demo_tenant"),
        sa.UniqueConstraint("dataset_key", name="uq_demo_tenant_bindings_dataset_key"),
        sa.CheckConstraint("demo_tenant_id > 0", name="ck_demo_tenant_bindings_demo_tenant_positive"),
        sa.CheckConstraint("version > 0", name="ck_demo_tenant_bindings_version_positive"),
        sa.CheckConstraint("dataset_key ~ '^[a-z0-9][a-z0-9_-]{0,63}$'", name="ck_demo_tenant_bindings_dataset_key_format"),
        sa.CheckConstraint("dataset_version ~ '^[a-z0-9][a-z0-9._-]{0,39}$'", name="ck_demo_tenant_bindings_dataset_version_format"),
        sa.CheckConstraint("status IN ('active','disabled')", name="ck_demo_tenant_bindings_status"),
        sa.CheckConstraint("(status = 'active' AND disabled_at IS NULL) OR (status = 'disabled' AND disabled_at IS NOT NULL)", name="ck_demo_tenant_bindings_disabled_state"),
        sa.CheckConstraint("updated_at >= bound_at", name="ck_demo_tenant_bindings_updated_time"),
        sa.CheckConstraint("disabled_at IS NULL OR disabled_at >= bound_at", name="ck_demo_tenant_bindings_disabled_time"),
        sa.CheckConstraint("status <> 'disabled' OR updated_by_user_id IS NOT NULL", name="ck_demo_tenant_bindings_disabled_updater"),
        schema="public",
    )

    op.create_table(
        "demo_tenant_binding_history",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("binding_version", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("before_snapshot", JSONB(), nullable=True),
        sa.Column("after_snapshot", JSONB(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_demo_tenant_binding_history"),
        sa.ForeignKeyConstraint(["tenant_id"], ["public.tenants.id"], name="fk_demo_tenant_binding_history_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["public.users.id"], name="fk_demo_tenant_binding_history_actor", ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "binding_version", name="uq_demo_tenant_binding_history_tenant_version"),
        sa.CheckConstraint("binding_version > 0", name="ck_demo_tenant_binding_history_version_positive"),
        sa.CheckConstraint("operation IN ('create','disable','replace')", name="ck_demo_tenant_binding_history_operation"),
        sa.CheckConstraint("(operation = 'create' AND binding_version = 1 AND before_snapshot IS NULL) OR (operation IN ('disable','replace') AND before_snapshot IS NOT NULL AND " + _snapshot_contract("before_snapshot") + " AND (before_snapshot->>'version')::integer = binding_version - 1)", name="ck_demo_tenant_binding_history_before"),
        sa.CheckConstraint(_snapshot_contract("after_snapshot") + " AND (after_snapshot->>'version')::integer = binding_version", name="ck_demo_tenant_binding_history_after"),
        sa.CheckConstraint("(after_snapshot->>'tenant_id')::bigint = tenant_id AND (after_snapshot->>'updated_by_user_id')::bigint = actor_user_id AND (before_snapshot IS NULL OR (before_snapshot->>'tenant_id')::bigint = tenant_id)", name="ck_demo_tenant_binding_history_links"),
        sa.CheckConstraint("(operation = 'create' AND after_snapshot->>'status' = 'active' AND (after_snapshot->>'bound_by_user_id')::bigint = actor_user_id) OR (operation = 'replace' AND before_snapshot->>'status' IN ('active','disabled') AND after_snapshot->>'status' = 'active') OR (operation = 'disable' AND before_snapshot->>'status' = 'active' AND after_snapshot->>'status' = 'disabled')", name="ck_demo_tenant_binding_history_transition"),
        sa.CheckConstraint("btrim(reason) <> ''", name="ck_demo_tenant_binding_history_reason"),
        schema="public",
    )
    op.execute("""
        CREATE FUNCTION public.reject_demo_tenant_binding_history_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'demo_tenant_binding_history is append-only';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_demo_tenant_binding_history_append_only
        BEFORE UPDATE OR DELETE ON public.demo_tenant_binding_history
        FOR EACH ROW EXECUTE FUNCTION public.reject_demo_tenant_binding_history_mutation()
    """)
    op.execute("""
        CREATE TRIGGER trg_demo_tenant_binding_history_no_truncate
        BEFORE TRUNCATE ON public.demo_tenant_binding_history
        FOR EACH STATEMENT EXECUTE FUNCTION public.reject_demo_tenant_binding_history_mutation()
    """)
    op.execute("""
        CREATE FUNCTION public.reject_demo_tenant_binding_delete()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'demo_tenant_bindings cannot be physically deleted';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_demo_tenant_bindings_no_delete
        BEFORE DELETE ON public.demo_tenant_bindings
        FOR EACH ROW EXECUTE FUNCTION public.reject_demo_tenant_binding_delete()
    """)


def downgrade() -> None:
    raise RuntimeError(
        "0097_demo_tenant_bindings is irreversible: retain binding audit history and disable routing"
    )
