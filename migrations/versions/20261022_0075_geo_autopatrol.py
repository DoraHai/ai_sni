"""Add compatible self-service patrol state, daily claims, audit and budget.

Existing customers stay legacy and disabled for self-service. No grants or
historical claims are inferred. Application rollback retains this schema.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0075_geo_autopatrol"
down_revision = "0074_geo_ticket_assignment"
branch_labels = None
depends_on = None


def upgrade():
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
    # Available for repository convention only; never part of application rollback.
    op.drop_table("geo_visibility_patrol_daily_budget")
    op.drop_index("ix_geo_patrol_events_tenant_id", table_name="geo_visibility_patrol_setting_events")
    op.drop_table("geo_visibility_patrol_setting_events")
    op.drop_index("uq_geo_patrol_tenant_auto_day", table_name="geo_visibility_patrol_runs")
    op.drop_column("geo_visibility_patrol_runs", "last_progress_at")
    op.drop_column("geo_visibility_patrol_runs", "auto_day")
    for name in ("manual_limit_revision", "manual_daily_limit", "blocked_reason", "last_changed_at",
                 "last_changed_by", "opened_by", "opened_at", "lock_reason", "admin_locked",
                 "revision", "owner_scope", "owner_grant_id", "owner_user_id", "self_service_enabled", "schedule_mode"):
        op.drop_column("geo_visibility_patrol_settings", name)
