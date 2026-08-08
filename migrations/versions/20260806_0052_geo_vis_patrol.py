"""GEO visibility auto patrol runs + settings.

Revision ID: 0052_geo_vis_patrol
Revises: 0051_geo_engine_sample
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0052_geo_vis_patrol"
down_revision = "0051_geo_engine_sample"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_visibility_patrol_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("trigger", sa.String(length=24), nullable=False, server_default="manual"),
        sa.Column("auto_persist", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("prefer_real", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("prompt_limit", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("engine_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("items", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_geo_visibility_patrol_runs_tenant_id",
        "geo_visibility_patrol_runs",
        ["tenant_id"],
    )
    op.create_index(
        "ix_geo_vis_patrol_runs_tenant_created",
        "geo_visibility_patrol_runs",
        ["tenant_id", "created_at"],
    )

    op.create_table(
        "geo_visibility_patrol_settings",
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("daily_hour", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("auto_persist", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("prefer_real", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("prompt_limit", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("engine_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("geo_visibility_patrol_settings")
    op.drop_index("ix_geo_vis_patrol_runs_tenant_created", table_name="geo_visibility_patrol_runs")
    op.drop_index("ix_geo_visibility_patrol_runs_tenant_id", table_name="geo_visibility_patrol_runs")
    op.drop_table("geo_visibility_patrol_runs")
