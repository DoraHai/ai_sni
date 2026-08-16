"""add conversion fields to search term reports.

Revision ID: 0061_search_term_conversions
Revises: 0060_keyword_candidate_presets
Create Date: 2026-08-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0061_search_term_conversions"
down_revision: Union[str, None] = "0060_keyword_candidate_presets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "search_term_reports",
        sa.Column("conversions", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "search_term_reports",
        sa.Column("cvr", sa.Numeric(8, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("search_term_reports", "cvr")
    op.drop_column("search_term_reports", "conversions")
