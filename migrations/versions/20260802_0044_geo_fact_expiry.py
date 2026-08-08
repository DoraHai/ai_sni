"""GEO fact expiry date.

Revision ID: 0044_geo_fact_expiry
Revises: 0043_geo_publishing_channels
Create Date: 2026-08-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0044_geo_fact_expiry"
down_revision: Union[str, None] = "0043_geo_publishing_channels"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("geo_facts", sa.Column("expires_at", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("geo_facts", "expires_at")
