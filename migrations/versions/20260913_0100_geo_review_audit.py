"""Persist tenant-, role- and version-bound GEO review events.

Revision ID: 0100_geo_review_audit
Revises: 0099_demo_fixture_registry
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0100_geo_review_audit"
down_revision = "0099_demo_fixture_registry"
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
    raise RuntimeError(
        "0100_geo_review_audit is irreversible: retain persisted human review evidence"
    )
