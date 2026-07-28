"""add keyword guide price (百度指导价 leftPriceGuide/mPriceGuide)

Revision ID: 0012_keyword_guide_price
Revises: 0011_suggestions
Create Date: 2026-06-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_keyword_guide_price"
down_revision: Union[str, None] = "0011_suggestions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("keywords", sa.Column("left_price_guide", sa.Numeric(6, 2), nullable=True))
    op.add_column("keywords", sa.Column("m_price_guide", sa.Numeric(6, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("keywords", "m_price_guide")
    op.drop_column("keywords", "left_price_guide")
