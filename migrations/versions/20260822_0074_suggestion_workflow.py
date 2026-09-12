"""Add internal ownership workflow to SEM suggestions.

Revision ID: 0074_suggestion_workflow
Revises: 0074_merge_geo_seo_heads
Create Date: 2026-08-22

Rebased 2026-08-22: originally chained to 0073_geo_schema_repair, but the
production database had already moved to 0074_merge_geo_seo_heads (which
itself merges 0073_geo_schema_repair with 0073_seo_distribution_variants)
via a separate, independently deployed SEO/GEO release before this
migration was applied anywhere. Re-pointing down_revision here avoids a
second, redundant merge migration since 0074_merge_geo_seo_heads already
is a strict superset ancestor. No DDL in this file changed.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0074_suggestion_workflow"
down_revision: Union[str, None] = "0074_merge_geo_seo_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("suggestions", sa.Column("handling_status", sa.String(length=24), nullable=False, server_default="todo"))
    op.add_column("suggestions", sa.Column("assignee_id", sa.BigInteger(), nullable=True))
    op.add_column("suggestions", sa.Column("due_at", sa.DateTime(), nullable=True))
    op.add_column("suggestions", sa.Column("workflow_updated_by", sa.BigInteger(), nullable=True))
    op.add_column("suggestions", sa.Column("workflow_updated_at", sa.DateTime(), nullable=True))
    op.create_foreign_key("fk_suggestions_assignee_id_users", "suggestions", "users", ["assignee_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_suggestions_workflow_updated_by_users", "suggestions", "users", ["workflow_updated_by"], ["id"], ondelete="SET NULL")
    op.create_index("ix_suggestions_assignee_id", "suggestions", ["assignee_id"])
    op.create_index("ix_suggestions_handling_status", "suggestions", ["handling_status"])
    op.alter_column("suggestions", "handling_status", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_suggestions_handling_status", table_name="suggestions")
    op.drop_index("ix_suggestions_assignee_id", table_name="suggestions")
    op.drop_constraint("fk_suggestions_workflow_updated_by_users", "suggestions", type_="foreignkey")
    op.drop_constraint("fk_suggestions_assignee_id_users", "suggestions", type_="foreignkey")
    op.drop_column("suggestions", "workflow_updated_at")
    op.drop_column("suggestions", "workflow_updated_by")
    op.drop_column("suggestions", "due_at")
    op.drop_column("suggestions", "assignee_id")
    op.drop_column("suggestions", "handling_status")
