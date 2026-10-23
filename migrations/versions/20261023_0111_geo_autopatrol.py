"""Canonical adoption of the retired GEO 0075 schema after shared revision 0110.

Unlike 0095, no reviewed already-applied 0075 state is known. Require every new
object to be absent, including on offline execution. Partial or complete existing
objects fail closed; do not stamp/adopt or infer historical claims. GEO keeps its
local 0075 for isolated chain tests only. Production uses this shared chain.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0111_geo_autopatrol"
down_revision = "0110_distribution_inbox"
branch_labels = None
depends_on = None


PREFLIGHT_SQL = (
    """DO $guard$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname=current_schema() AND c.relname='geo_visibility_patrol_settings' AND c.relkind='r')
     OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname=current_schema() AND c.relname='geo_visibility_patrol_runs' AND c.relkind='r') THEN
    RAISE EXCEPTION '0111 requires ordinary settings and runs tables';
  END IF;
END $guard$""",
    """LOCK TABLE geo_visibility_patrol_settings, geo_visibility_patrol_runs IN ACCESS EXCLUSIVE MODE""",
    """DO $guard$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_catalog.pg_attribute a
    JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname=current_schema() AND a.attnum>0 AND NOT a.attisdropped
      AND ((c.relname='geo_visibility_patrol_settings' AND a.attname IN ('schedule_mode','self_service_enabled','owner_user_id','owner_grant_id','owner_scope','revision','admin_locked','lock_reason','opened_at','opened_by','last_changed_by','last_changed_at','blocked_reason','manual_daily_limit','manual_limit_revision'))
        OR (c.relname='geo_visibility_patrol_runs' AND a.attname IN ('auto_day','last_progress_at')))
  ) OR EXISTS (
    SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname=current_schema() AND c.relname IN (
      'geo_visibility_patrol_setting_events','geo_visibility_patrol_daily_budget',
      'geo_visibility_patrol_setting_events_id_seq','geo_visibility_patrol_setting_events_pkey',
      'geo_visibility_patrol_daily_budget_pkey','ix_geo_patrol_events_tenant_id','uq_geo_patrol_tenant_auto_day')
  ) THEN
    RAISE EXCEPTION '0111 refuses existing or partial autopatrol objects; no automatic adoption';
  END IF;
END $guard$""",
)


def upgrade():
    for statement in PREFLIGHT_SQL:
        op.execute(sa.text(statement))
    columns = [
        sa.Column("schedule_mode", sa.String(32), nullable=False, server_default="legacy"),
        sa.Column("self_service_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("owner_user_id", sa.BigInteger(), nullable=True),
        sa.Column("owner_grant_id", sa.BigInteger(), nullable=True),
        sa.Column("owner_scope", postgresql.JSONB(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("admin_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("lock_reason", sa.String(500), nullable=True),
        sa.Column("opened_at", sa.DateTime(), nullable=True),
        sa.Column("opened_by", sa.BigInteger(), nullable=True),
        sa.Column("last_changed_by", sa.BigInteger(), nullable=True),
        sa.Column("last_changed_at", sa.DateTime(), nullable=True),
        sa.Column("blocked_reason", sa.String(64), nullable=True),
        sa.Column("manual_daily_limit", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("manual_limit_revision", sa.Integer(), nullable=False, server_default="0"),
    ]
    for column in columns:
        op.add_column("geo_visibility_patrol_settings", column)
    op.add_column("geo_visibility_patrol_runs", sa.Column("auto_day", sa.Date(), nullable=True))
    op.add_column("geo_visibility_patrol_runs", sa.Column("last_progress_at", sa.DateTime(), nullable=True))
    op.create_index("uq_geo_patrol_tenant_auto_day", "geo_visibility_patrol_runs",
                    ["tenant_id", "auto_day"], unique=True,
                    postgresql_where=sa.text("auto_day IS NOT NULL"))
    op.create_table(
        "geo_visibility_patrol_setting_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("actor_role", sa.String(32), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=False),
        sa.Column("after", postgresql.JSONB(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_geo_patrol_events_tenant_id", "geo_visibility_patrol_setting_events", ["tenant_id", "id"])
    op.create_table(
        "geo_visibility_patrol_daily_budget",
        sa.Column("budget_day", sa.Date(), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    raise RuntimeError("0111_geo_autopatrol is irreversible; retain audit and daily claims")
