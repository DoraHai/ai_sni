"""Persist the source site page for SEO content tasks.

Revision ID: 0075_seo_content_source_page
Revises: 0074_merge_geo_seo_heads
Create Date: 2026-08-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0075_seo_content_source_page"
down_revision: Union[str, None] = "0074_merge_geo_seo_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "seo_content_assets",
        sa.Column("source_page_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_seo_content_assets_source_page_id",
        "seo_content_assets",
        "seo_site_pages",
        ["source_page_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_seo_content_assets_source_page_id",
        "seo_content_assets",
        ["source_page_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_seo_content_asset_source_page",
        "seo_content_assets",
        ["tenant_id", "site_id", "source_page_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_seo_content_asset_source_page",
        "seo_content_assets",
        type_="unique",
    )
    op.drop_index(
        "ix_seo_content_assets_source_page_id",
        table_name="seo_content_assets",
    )
    op.drop_constraint(
        "fk_seo_content_assets_source_page_id",
        "seo_content_assets",
        type_="foreignkey",
    )
    op.drop_column("seo_content_assets", "source_page_id")
