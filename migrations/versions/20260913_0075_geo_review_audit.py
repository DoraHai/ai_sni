"""Persist tenant-, role- and version-bound GEO review events.

Revision ID: 0075_geo_review_audit
Revises: 0074_geo_ticket_assignment
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0075_geo_review_audit"
down_revision = "0074_geo_ticket_assignment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "geo_content_tasks",
        sa.Column(
            "review_audit",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("geo_content_tasks", "review_audit")
