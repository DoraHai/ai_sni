"""Repair missing SEO rewrite workflow columns.

Revision ID: 0065_seo_rewrite_schema_repair
Revises: 0064_merge_geo_sem_heads
Create Date: 2026-08-17

Some deployed databases were stamped past ``0057_seo_rewrite_workflow``
without receiving its table alterations.  Keep this repair idempotent so it
is safe for both affected databases and databases whose schema is complete.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0065_seo_rewrite_schema_repair"
down_revision: Union[str, None] = "0064_merge_geo_sem_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            ALTER TABLE seo_content_assets
                ADD COLUMN IF NOT EXISTS source_text TEXT,
                ADD COLUMN IF NOT EXISTS rewrite_progress SMALLINT,
                ADD COLUMN IF NOT EXISTS originality_score SMALLINT,
                ADD COLUMN IF NOT EXISTS target_platforms JSONB,
                ADD COLUMN IF NOT EXISTS version_count INTEGER NOT NULL DEFAULT 1
            """
        )
    )


def downgrade() -> None:
    # These columns belong to the historical 0057 migration.  Removing them
    # would make the schema inconsistent with the 0064 model state, so a
    # downgrade only removes this repair revision marker.
    pass
