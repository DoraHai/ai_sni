"""add suggestions (AI 调价建议)

Revision ID: 0011_suggestions
Revises: 0010_users
Create Date: 2026-06-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_suggestions"
down_revision: Union[str, None] = "0010_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "suggestions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("rule_code", sa.String(30), nullable=False),
        sa.Column("suggestion_type", sa.String(20), nullable=False),
        sa.Column("priority", sa.String(4), nullable=False),
        sa.Column("confidence", sa.String(10), nullable=False),
        sa.Column("current_bid", sa.Numeric(8, 2), nullable=True),
        sa.Column("suggested_bid", sa.Numeric(8, 2), nullable=True),
        sa.Column("change_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("signals", postgresql.JSONB(), nullable=True),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("keyword_id", sa.BigInteger(), nullable=True),
        sa.Column("keyword", sa.Text(), nullable=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=True),
        sa.Column("campaign_name", sa.Text(), nullable=True),
        sa.Column("adgroup_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("adopted_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "tenant_id",
            "keyword_id",
            "report_date",
            name="uq_suggestions_tenant_kw_date",
        ),
    )
    op.create_index(
        "ix_suggestions_tenant_status", "suggestions", ["tenant_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_suggestions_tenant_status", table_name="suggestions")
    op.drop_table("suggestions")
