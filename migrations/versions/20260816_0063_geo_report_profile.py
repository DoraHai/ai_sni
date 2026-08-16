"""competitor reports + business profile

Revision ID: 0063_geo_report_profile
Revises: 0062_geo_metric_period
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0063_geo_report_profile"
down_revision: Union[str, None] = "0062_geo_metric_period"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "geo_optimization_businesses",
        sa.Column("profile", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_table(
        "geo_competitor_reports",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "business_id",
            sa.BigInteger(),
            sa.ForeignKey("geo_optimization_businesses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "period_id",
            sa.BigInteger(),
            sa.ForeignKey("geo_optimization_periods.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("competitor", sa.String(120), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("insight", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("markdown", sa.Text(), nullable=True),
        sa.Column("source_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("platform_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("confirmed_by", sa.BigInteger(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_geo_competitor_reports_tenant_id", "geo_competitor_reports", ["tenant_id"])
    op.create_index("ix_geo_competitor_reports_competitor", "geo_competitor_reports", ["competitor"])
    op.create_index("ix_geo_competitor_reports_business_id", "geo_competitor_reports", ["business_id"])
    op.create_index("ix_geo_competitor_reports_period_id", "geo_competitor_reports", ["period_id"])

    op.create_table(
        "geo_competitor_report_versions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "report_id",
            sa.BigInteger(),
            sa.ForeignKey("geo_competitor_reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=True),
        sa.Column("insight", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("report_id", "version_no", name="uq_geo_comp_report_ver"),
    )
    op.create_index(
        "ix_geo_competitor_report_versions_report_id",
        "geo_competitor_report_versions",
        ["report_id"],
    )


def downgrade() -> None:
    op.drop_table("geo_competitor_report_versions")
    op.drop_table("geo_competitor_reports")
    op.drop_column("geo_optimization_businesses", "profile")
