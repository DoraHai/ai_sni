"""SEO content review workflow.

Revision ID: 0079_seo_content_review_workflow
Revises: 0078_seo_site_data_repairs
"""

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0079_seo_content_review_workflow"
down_revision: Union[str, None] = "0078_seo_site_data_repairs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("seo_content_assets", sa.Column("review_submitted_by", sa.BigInteger(), nullable=True))
    op.add_column("seo_content_assets", sa.Column("review_submitted_at", sa.DateTime(), nullable=True))
    op.add_column("seo_content_assets", sa.Column("review_note", sa.Text(), nullable=True))
    op.add_column("seo_content_assets", sa.Column("reviewed_by", sa.BigInteger(), nullable=True))
    op.add_column("seo_content_assets", sa.Column("reviewed_at", sa.DateTime(), nullable=True))
    op.create_index(
        "ix_seo_content_assets_tenant_review",
        "seo_content_assets",
        ["tenant_id", "status", "review_submitted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_seo_content_assets_tenant_review", table_name="seo_content_assets")
    op.drop_column("seo_content_assets", "reviewed_at")
    op.drop_column("seo_content_assets", "reviewed_by")
    op.drop_column("seo_content_assets", "review_note")
    op.drop_column("seo_content_assets", "review_submitted_at")
    op.drop_column("seo_content_assets", "review_submitted_by")
