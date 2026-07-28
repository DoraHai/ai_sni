"""add keywords dimension table + tenants.brand_terms

Revision ID: 0004_keywords
Revises: 0003_alerts
Create Date: 2026-06-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_keywords"
down_revision: Union[str, None] = "0003_alerts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("brand_terms", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_table(
        "keywords",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "baidu_account_id", sa.BigInteger(), sa.ForeignKey("baidu_accounts.id"), nullable=True
        ),
        sa.Column("keyword_id", sa.BigInteger(), nullable=False),
        sa.Column("keyword", sa.Text(), nullable=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=True),
        sa.Column("adgroup_id", sa.BigInteger(), nullable=True),
        sa.Column("match_type", sa.SmallInteger(), nullable=True),
        sa.Column("phrase_type", sa.SmallInteger(), nullable=True),
        sa.Column("price", sa.Numeric(8, 2), nullable=True),
        sa.Column("pause", sa.Boolean(), nullable=True),
        sa.Column("status", sa.SmallInteger(), nullable=True),
        sa.Column("tabs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("quality", sa.SmallInteger(), nullable=True),
        sa.Column("baidu_create_time", sa.DateTime(), nullable=True),
        sa.Column("first_seen_date", sa.Date(), nullable=True),
        sa.Column("total_impression", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("category", sa.String(10), nullable=True),
        sa.Column("category_source", sa.String(10), nullable=False, server_default="auto"),
        sa.Column("category_updated_at", sa.DateTime(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "keyword_id", name="uq_keywords_tenant_kw"),
    )
    op.create_index(
        "ix_keywords_tenant_category", "keywords", ["tenant_id", "category"]
    )


def downgrade() -> None:
    op.drop_index("ix_keywords_tenant_category", table_name="keywords")
    op.drop_table("keywords")
    op.drop_column("tenants", "brand_terms")
