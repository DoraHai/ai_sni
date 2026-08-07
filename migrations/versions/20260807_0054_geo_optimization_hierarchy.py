"""GEO 三级结构：优化业务 / 单元 + 意图词 unit_id + 按天汇总。

Revision ID: 0054_geo_opt_hierarchy
Revises: 0053_patrol_window
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0054_geo_opt_hierarchy"
down_revision = "0053_patrol_window"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_optimization_businesses",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "name", name="uq_geo_opt_business_tenant_name"),
    )
    op.create_index(
        "ix_geo_optimization_businesses_tenant_id",
        "geo_optimization_businesses",
        ["tenant_id"],
    )

    op.create_table(
        "geo_optimization_units",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "business_id",
            sa.BigInteger(),
            sa.ForeignKey("geo_optimization_businesses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("keyword", sa.String(200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "business_id", "name", name="uq_geo_opt_unit_biz_name"),
    )
    op.create_index(
        "ix_geo_optimization_units_tenant_id",
        "geo_optimization_units",
        ["tenant_id"],
    )
    op.create_index(
        "ix_geo_optimization_units_business_id",
        "geo_optimization_units",
        ["business_id"],
    )

    op.add_column(
        "geo_prompts",
        sa.Column(
            "unit_id",
            sa.BigInteger(),
            sa.ForeignKey("geo_optimization_units.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_geo_prompts_unit_id", "geo_prompts", ["unit_id"])

    op.create_table(
        "geo_daily_metrics",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("scope_key", sa.String(80), nullable=False, server_default="t"),
        sa.Column("business_id", sa.BigInteger(), nullable=True),
        sa.Column("unit_id", sa.BigInteger(), nullable=True),
        sa.Column("engine", sa.String(64), nullable=True),
        sa.Column("snapshots_visibility", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("snapshots_probe", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("brand_mentions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("brand_probe_hits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("top1_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("distinct_cited_domains", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("citation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("brand_mention_rate", sa.Float(), nullable=True),
        sa.Column("brand_probe_recognition_rate", sa.Float(), nullable=True),
        sa.Column("top1_rate", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "tenant_id",
            "metric_date",
            "scope_key",
            name="uq_geo_daily_metric_scope",
        ),
    )
    op.create_index("ix_geo_daily_metrics_tenant_id", "geo_daily_metrics", ["tenant_id"])
    op.create_index("ix_geo_daily_metrics_metric_date", "geo_daily_metrics", ["metric_date"])
    op.create_index("ix_geo_daily_metrics_business_id", "geo_daily_metrics", ["business_id"])
    op.create_index("ix_geo_daily_metrics_unit_id", "geo_daily_metrics", ["unit_id"])


def downgrade() -> None:
    op.drop_table("geo_daily_metrics")
    op.drop_index("ix_geo_prompts_unit_id", table_name="geo_prompts")
    op.drop_column("geo_prompts", "unit_id")
    op.drop_table("geo_optimization_units")
    op.drop_table("geo_optimization_businesses")
