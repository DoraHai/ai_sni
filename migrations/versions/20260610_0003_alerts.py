"""add alerts

Revision ID: 0003_alerts
Revises: 0002_kw_report_snapshots
Create Date: 2026-06-10

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_alerts"
down_revision: Union[str, None] = "0002_kw_report_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("rule_code", sa.String(20), nullable=False),
        sa.Column("priority", sa.String(4), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("keyword_id", sa.BigInteger(), nullable=True),
        sa.Column("keyword", sa.Text(), nullable=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=True),
        sa.Column("campaign_name", sa.Text(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("detected_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "tenant_id",
            "rule_code",
            "keyword_id",
            "report_date",
            name="uq_alerts_tenant_rule_kw_date",
        ),
    )
    op.create_index(
        "ix_alerts_tenant_status",
        "alerts",
        ["tenant_id", "status", sa.text("report_date DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_alerts_tenant_status", table_name="alerts")
    op.drop_table("alerts")
