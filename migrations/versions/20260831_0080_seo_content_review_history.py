"""SEO content review event history.

Revision ID: 0080_seo_content_review_history
Revises: 0079_seo_content_review_workflow
"""

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0080_seo_content_review_history"
down_revision: Union[str, None] = "0079_seo_content_review_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seo_content_review_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("site_id", sa.BigInteger(), nullable=True),
        sa.Column("content_asset_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("from_status", sa.String(length=24), nullable=False),
        sa.Column("to_status", sa.String(length=24), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["content_asset_id"], ["seo_content_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["seo_sites.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_seo_content_review_events_tenant_id", "seo_content_review_events", ["tenant_id"])
    op.create_index("ix_seo_content_review_events_site_id", "seo_content_review_events", ["site_id"])
    op.create_index("ix_seo_content_review_events_content_asset_id", "seo_content_review_events", ["content_asset_id"])
    op.create_index(
        "ix_seo_content_review_events_tenant_asset_created",
        "seo_content_review_events",
        ["tenant_id", "content_asset_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_seo_content_review_events_tenant_asset_created", table_name="seo_content_review_events")
    op.drop_index("ix_seo_content_review_events_content_asset_id", table_name="seo_content_review_events")
    op.drop_index("ix_seo_content_review_events_site_id", table_name="seo_content_review_events")
    op.drop_index("ix_seo_content_review_events_tenant_id", table_name="seo_content_review_events")
    op.drop_table("seo_content_review_events")
