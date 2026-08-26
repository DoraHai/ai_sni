"""add preset fields to keyword candidates.

Revision ID: 0060_keyword_candidate_presets
Revises: 0059_alert_entity_ref
Create Date: 2026-08-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0060_keyword_candidate_presets"
down_revision: Union[str, None] = "0059_alert_entity_ref"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "keyword_candidates",
        sa.Column("preset_price", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "keyword_candidates",
        sa.Column("preset_match_mode", sa.String(length=10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("keyword_candidates", "preset_match_mode")
    op.drop_column("keyword_candidates", "preset_price")
