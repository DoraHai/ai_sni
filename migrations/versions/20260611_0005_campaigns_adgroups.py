"""add campaigns / adgroups dimension tables

Revision ID: 0005_campaigns_adgroups
Revises: 0004_keywords
Create Date: 2026-06-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_campaigns_adgroups"
down_revision: Union[str, None] = "0004_keywords"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "baidu_account_id", sa.BigInteger(), sa.ForeignKey("baidu_accounts.id"), nullable=True
        ),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_name", sa.Text(), nullable=True),
        sa.Column("budget", sa.Numeric(12, 2), nullable=True),
        sa.Column("pause", sa.Boolean(), nullable=True),
        sa.Column("status", sa.SmallInteger(), nullable=True),
        sa.Column("equipment_type", sa.SmallInteger(), nullable=True),
        sa.Column("region_target", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("schedule", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("region_price_factor", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "schedule_price_factors", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("negative_words", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("exact_negative_words", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("baidu_create_time", sa.DateTime(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "campaign_id", name="uq_campaigns_tenant_camp"),
    )
    op.create_table(
        "adgroups",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "baidu_account_id", sa.BigInteger(), sa.ForeignKey("baidu_accounts.id"), nullable=True
        ),
        sa.Column("adgroup_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=True),
        sa.Column("adgroup_name", sa.Text(), nullable=True),
        sa.Column("max_price", sa.Numeric(8, 2), nullable=True),
        sa.Column("pause", sa.Boolean(), nullable=True),
        sa.Column("status", sa.SmallInteger(), nullable=True),
        sa.Column("negative_words", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("exact_negative_words", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "adgroup_id", name="uq_adgroups_tenant_adg"),
    )


def downgrade() -> None:
    op.drop_table("adgroups")
    op.drop_table("campaigns")
