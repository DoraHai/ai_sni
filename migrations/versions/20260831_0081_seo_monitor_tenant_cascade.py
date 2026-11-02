"""Align tenant deletion for SEO-owned rows and add backlink monitoring state.

Revision ID: 0081_seo_monitor_cascade
Revises: 0080_seo_content_review_history
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0081_seo_monitor_cascade"
down_revision: Union[str, None] = "0080_seo_content_review_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = (
    "seo_keyword_assets",
    "seo_rank_snapshots",
    "seo_brand_assets",
    "seo_serp_results",
    "seo_site_pages",
    "seo_content_assets",
    "seo_distribution_connections",
    "seo_distribution_variants",
    "seo_content_publications",
    "seo_publish_attempts",
    "seo_internal_links",
    "seo_backlinks",
    "seo_competitors",
    "seo_competitor_events",
)


def _replace_tenant_fk(table_name: str, *, ondelete: str | None) -> None:
    constraint_name = f"{table_name}_tenant_id_fkey"
    op.drop_constraint(constraint_name, table_name, type_="foreignkey")
    op.create_foreign_key(
        constraint_name,
        table_name,
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete=ondelete,
    )


def upgrade() -> None:
    for table_name in TABLES:
        _replace_tenant_fk(table_name, ondelete="CASCADE")
    op.add_column("seo_backlinks", sa.Column("last_checked_at", sa.DateTime(), nullable=True))
    op.add_column(
        "seo_backlinks",
        sa.Column("missing_checks", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("seo_backlinks", "missing_checks")
    op.drop_column("seo_backlinks", "last_checked_at")
    for table_name in reversed(TABLES):
        _replace_tenant_fk(table_name, ondelete=None)
