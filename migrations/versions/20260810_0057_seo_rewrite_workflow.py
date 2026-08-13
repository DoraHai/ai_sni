"""SEO rewrite workflow fields.

Revision ID: 0057_seo_rewrite_workflow
Revises: 0056_seo_foundation
Create Date: 2026-08-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0057_seo_rewrite_workflow"
down_revision: Union[str, None] = "0056_seo_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("seo_content_assets", sa.Column("source_text", sa.Text()))
    op.add_column("seo_content_assets", sa.Column("rewrite_progress", sa.SmallInteger()))
    op.add_column("seo_content_assets", sa.Column("originality_score", sa.SmallInteger()))
    op.add_column("seo_content_assets", sa.Column("target_platforms", postgresql.JSONB()))
    op.add_column(
        "seo_content_assets",
        sa.Column("version_count", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("seo_content_assets", "version_count")
    op.drop_column("seo_content_assets", "target_platforms")
    op.drop_column("seo_content_assets", "originality_score")
    op.drop_column("seo_content_assets", "rewrite_progress")
    op.drop_column("seo_content_assets", "source_text")
