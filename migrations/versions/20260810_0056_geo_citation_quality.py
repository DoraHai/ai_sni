"""GEO answer snapshot citation quality fields.

Revision ID: 0056_geo_citation_quality
Revises: 0055_geo_channel_polish_prompts
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0056_geo_citation_quality"
down_revision: Union[str, None] = "0055_geo_channel_polish_prompts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "geo_answer_snapshots",
        sa.Column(
            "citation_format",
            sa.String(length=16),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "geo_answer_snapshots",
        sa.Column(
            "citation_accuracy",
            sa.String(length=16),
            nullable=False,
            server_default="unknown",
        ),
    )


def downgrade() -> None:
    op.drop_column("geo_answer_snapshots", "citation_accuracy")
    op.drop_column("geo_answer_snapshots", "citation_format")
