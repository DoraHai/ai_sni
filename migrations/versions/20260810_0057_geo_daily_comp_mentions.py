"""GEO daily metrics competitor mentions JSONB.

Revision ID: 0057_geo_daily_comp_mentions
Revises: 0056_geo_citation_quality
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0057_geo_daily_comp_mentions"
down_revision: Union[str, None] = "0056_geo_citation_quality"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "geo_daily_metrics",
        sa.Column(
            "competitor_mentions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "geo_daily_metrics",
        sa.Column("top_competitor", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "geo_daily_metrics",
        sa.Column("top_competitor_rate", sa.Float(), nullable=True),
    )
    op.add_column(
        "geo_daily_metrics",
        sa.Column(
            "any_competitor_mentions",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("geo_daily_metrics", "any_competitor_mentions")
    op.drop_column("geo_daily_metrics", "top_competitor_rate")
    op.drop_column("geo_daily_metrics", "top_competitor")
    op.drop_column("geo_daily_metrics", "competitor_mentions")
