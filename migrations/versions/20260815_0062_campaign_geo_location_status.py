"""add campaign geo location status.

Revision ID: 0062_campaign_geo_status
Revises: 0061_search_term_conversions
Create Date: 2026-08-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0062_campaign_geo_status"
down_revision: Union[str, None] = "0061_search_term_conversions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("geo_location_status", sa.SmallInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("campaigns", "geo_location_status")
