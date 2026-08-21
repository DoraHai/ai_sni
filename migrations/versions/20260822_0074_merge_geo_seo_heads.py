"""Merge the deployed GEO repair and SEO distribution variant heads.

Revision ID: 0074_merge_geo_seo_heads
Revises: 0073_geo_schema_repair, 0073_seo_distribution_variants
Create Date: 2026-08-22

This revision only reconciles Alembic history. The parent revisions own all
schema changes; this merge must never add DDL or data mutations.
"""

from typing import Sequence, Union


revision: str = "0074_merge_geo_seo_heads"
down_revision: Union[str, tuple[str, str]] = (
    "0073_geo_schema_repair",
    "0073_seo_distribution_variants",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
