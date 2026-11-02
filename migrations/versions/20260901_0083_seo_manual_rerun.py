"""Record the user who requested a manual SEO automation run.

Revision ID: 0083_seo_manual_rerun
Revises: 0082_seo_automation_runs
"""

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0083_seo_manual_rerun"
down_revision: Union[str, None] = "0082_seo_automation_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "seo_automation_runs",
        sa.Column("requested_by", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_seo_automation_runs_requested_by_users",
        "seo_automation_runs",
        "users",
        ["requested_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_seo_automation_runs_requested_by",
        "seo_automation_runs",
        ["requested_by"],
    )


def downgrade() -> None:
    op.drop_index("ix_seo_automation_runs_requested_by", table_name="seo_automation_runs")
    op.drop_constraint(
        "fk_seo_automation_runs_requested_by_users",
        "seo_automation_runs",
        type_="foreignkey",
    )
    op.drop_column("seo_automation_runs", "requested_by")
