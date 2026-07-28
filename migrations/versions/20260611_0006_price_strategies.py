"""add price_strategies (优化排名出价策略)

Revision ID: 0006_price_strategies
Revises: 0005_campaigns_adgroups
Create Date: 2026-06-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_price_strategies"
down_revision: Union[str, None] = "0005_campaigns_adgroups"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "price_strategies",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "baidu_account_id", sa.BigInteger(), sa.ForeignKey("baidu_accounts.id"), nullable=True
        ),
        sa.Column("strategy_id", sa.BigInteger(), nullable=False),
        sa.Column("strategy_name", sa.Text(), nullable=True),
        sa.Column("strategy_type", sa.SmallInteger(), nullable=True),
        sa.Column("target_rank", sa.SmallInteger(), nullable=True),
        sa.Column("price_factor", sa.Numeric(4, 2), nullable=True),
        sa.Column("is_pause", sa.Boolean(), nullable=True),
        sa.Column("campaign_bindings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id", "strategy_id", name="uq_price_strategies_tenant_strat"
        ),
    )


def downgrade() -> None:
    op.drop_table("price_strategies")
