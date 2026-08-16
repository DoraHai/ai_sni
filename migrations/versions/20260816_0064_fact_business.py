"""facts.business_id for business-scoped evidence

Revision ID: 0064_fact_business
Revises: 0063_geo_report_profile
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0064_fact_business"
down_revision: Union[str, None] = "0063_geo_report_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "geo_facts",
        sa.Column(
            "business_id",
            sa.BigInteger(),
            sa.ForeignKey("geo_optimization_businesses.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_geo_facts_business_id", "geo_facts", ["business_id"])


def downgrade() -> None:
    op.drop_index("ix_geo_facts_business_id", table_name="geo_facts")
    op.drop_column("geo_facts", "business_id")
