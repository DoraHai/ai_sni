"""GEO channel adapt: variant adapt_meta

Revision ID: 0040_geo_channel_adapt
Revises: 0039_geo_wave_b2
Create Date: 2026-07-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0040_geo_channel_adapt"
down_revision: Union[str, None] = "0039_geo_wave_b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "geo_channel_variants",
        sa.Column("adapt_meta", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("geo_channel_variants", "adapt_meta")
