"""Add sample_mode and optional OpenAI-compat creds on tracking engines.

Revision ID: 0051_geo_engine_sample
Revises: 0050_geo_expand_runs
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0051_geo_engine_sample"
down_revision = "0050_geo_expand_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "geo_tracking_engines",
        sa.Column(
            "sample_mode",
            sa.String(length=32),
            nullable=False,
            server_default="mock_persona",
        ),
    )
    op.add_column(
        "geo_tracking_engines",
        sa.Column("api_base_url", sa.String(length=300), nullable=True),
    )
    op.add_column(
        "geo_tracking_engines",
        sa.Column("model", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "geo_tracking_engines",
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("geo_tracking_engines", "api_key_encrypted")
    op.drop_column("geo_tracking_engines", "model")
    op.drop_column("geo_tracking_engines", "api_base_url")
    op.drop_column("geo_tracking_engines", "sample_mode")
