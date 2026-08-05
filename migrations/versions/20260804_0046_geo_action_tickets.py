"""GEO D3: action tickets for auto/manual verify."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0046_geo_action_tickets"
down_revision = "0045_geo_d0_d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_action_tickets",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "audit_id",
            sa.BigInteger(),
            sa.ForeignKey("geo_audit_runs.id"),
            nullable=True,
        ),
        sa.Column("advice_code", sa.String(length=64), nullable=True),
        sa.Column("content_task_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "media_placement_id",
            sa.BigInteger(),
            sa.ForeignKey("geo_media_placements.id"),
            nullable=True,
        ),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("action", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="todo"),
        sa.Column(
            "acceptance_type",
            sa.String(length=16),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("acceptance_check", sa.String(length=128), nullable=True),
        sa.Column("acceptance_desc", sa.Text(), nullable=True),
        sa.Column("baseline_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("progress_first", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("progress", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_verify_at", sa.DateTime(), nullable=True),
        sa.Column("last_verdict", sa.String(length=16), nullable=True),
        sa.Column("last_note", sa.Text(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_geo_action_tickets_tenant_id",
        "geo_action_tickets",
        ["tenant_id"],
    )
    op.create_index(
        "ix_geo_action_tickets_audit_id",
        "geo_action_tickets",
        ["audit_id"],
    )
    op.create_index(
        "ix_geo_action_tickets_tenant_status",
        "geo_action_tickets",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_geo_action_tickets_tenant_status", table_name="geo_action_tickets")
    op.drop_index("ix_geo_action_tickets_audit_id", table_name="geo_action_tickets")
    op.drop_index("ix_geo_action_tickets_tenant_id", table_name="geo_action_tickets")
    op.drop_table("geo_action_tickets")
