"""Merge the latest GEO and SEM migration branches.

Revision ID: 0064_merge_geo_sem_heads
Revises: 0064_fact_business, 0063_seo_serp_brand_assets
"""

from typing import Sequence, Union


revision: str = "0064_merge_geo_sem_heads"
down_revision: Union[str, tuple[str, str], None] = (
    "0064_fact_business",
    "0063_seo_serp_brand_assets",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Join both histories; schema changes belong to the parent revisions."""


def downgrade() -> None:
    """Split back to both parent heads without changing schema objects."""
