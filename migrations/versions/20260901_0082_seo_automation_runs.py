"""Add lightweight tenant-scoped SEO automation run summaries.

Revision ID: 0082_seo_automation_runs
Revises: 0081_seo_monitor_cascade
"""

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0082_seo_automation_runs"
down_revision: Union[str, None] = "0081_seo_monitor_cascade"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seo_automation_runs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("site_id", sa.BigInteger(), nullable=True),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("trigger_type", sa.String(length=16), nullable=False, server_default="scheduled"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="running"),
        sa.Column("planned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["site_id"], ["seo_sites.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_seo_automation_runs_tenant_id", "seo_automation_runs", ["tenant_id"])
    op.create_index("ix_seo_automation_runs_site_id", "seo_automation_runs", ["site_id"])
    op.create_index("ix_seo_automation_runs_job_type", "seo_automation_runs", ["job_type"])
    op.create_index("ix_seo_automation_runs_status", "seo_automation_runs", ["status"])
    op.create_index(
        "ix_seo_automation_runs_tenant_job_started",
        "seo_automation_runs",
        ["tenant_id", "job_type", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_seo_automation_runs_tenant_job_started", table_name="seo_automation_runs")
    op.drop_index("ix_seo_automation_runs_status", table_name="seo_automation_runs")
    op.drop_index("ix_seo_automation_runs_job_type", table_name="seo_automation_runs")
    op.drop_index("ix_seo_automation_runs_site_id", table_name="seo_automation_runs")
    op.drop_index("ix_seo_automation_runs_tenant_id", table_name="seo_automation_runs")
    op.drop_table("seo_automation_runs")
