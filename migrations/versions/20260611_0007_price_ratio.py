"""add price_ratio (移动出价比例) to campaigns / adgroups

Revision ID: 0007_price_ratio
Revises: 0006_price_strategies
Create Date: 2026-06-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_price_ratio"
down_revision: Union[str, None] = "0006_price_strategies"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("price_ratio", sa.Numeric(6, 2), nullable=True))
    op.add_column("adgroups", sa.Column("price_ratio", sa.Numeric(6, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("adgroups", "price_ratio")
    op.drop_column("campaigns", "price_ratio")
