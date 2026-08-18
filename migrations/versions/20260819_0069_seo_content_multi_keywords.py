"""Add multiple target keywords to SEO content assets.

Revision ID: 0069_seo_content_keywords
Revises: 0068_seo_crawler
Create Date: 2026-08-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0069_seo_content_keywords"
down_revision: Union[str, None] = "0068_seo_crawler"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "seo_content_assets",
        sa.Column("keyword_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.execute(
        """
        UPDATE seo_content_assets
        SET keyword_ids = jsonb_build_array(keyword_id)
        WHERE keyword_id IS NOT NULL AND keyword_ids IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("seo_content_assets", "keyword_ids")
