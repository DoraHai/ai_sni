"""GEO Wave C: snapshot competitors / position / sentiment

Revision ID: 0041_geo_wave_c
Revises: 0040_geo_channel_adapt
Create Date: 2026-07-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0041_geo_wave_c"
down_revision: Union[str, None] = "0040_geo_channel_adapt"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "geo_answer_snapshots",
        sa.Column(
            "competitors",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "geo_answer_snapshots",
        sa.Column(
            "brand_position",
            sa.String(length=16),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "geo_answer_snapshots",
        sa.Column(
            "sentiment",
            sa.String(length=16),
            nullable=False,
            server_default="unknown",
        ),
    )


def downgrade() -> None:
    op.drop_column("geo_answer_snapshots", "sentiment")
    op.drop_column("geo_answer_snapshots", "brand_position")
    op.drop_column("geo_answer_snapshots", "competitors")
