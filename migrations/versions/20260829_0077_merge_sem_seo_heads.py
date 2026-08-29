"""Merge the deployed SEM head with the SEO content source branch.

Revision ID: 0077_merge_sem_seo_heads
Revises: 0076_oauth_rebind_intent, 0075_seo_content_source_page
Create Date: 2026-08-29
"""

from typing import Sequence, Union


revision: str = "0077_merge_sem_seo_heads"
down_revision: Union[str, Sequence[str], None] = (
    "0076_oauth_rebind_intent",
    "0075_seo_content_source_page",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
