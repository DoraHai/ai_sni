"""Allow queued SEO crawl runs before background execution starts.

Revision ID: 0084_seo_crawl_queued_status
Revises: 0083_seo_manual_rerun
"""

from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0084_seo_crawl_queued_status"
down_revision: Union[str, None] = "0083_seo_manual_rerun"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_seo_crawl_run_status",
        "seo_crawl_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_seo_crawl_run_status",
        "seo_crawl_runs",
        "status IN ('queued','running','completed','partial','failed')",
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE seo_crawl_runs
            SET status = 'failed',
                error_summary = COALESCE(
                    error_summary,
                    '任务因数据库版本回退而终止'
                ),
                completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP)
            WHERE status = 'queued'
            """
        )
    )
    op.drop_constraint(
        "ck_seo_crawl_run_status",
        "seo_crawl_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_seo_crawl_run_status",
        "seo_crawl_runs",
        "status IN ('running','completed','partial','failed')",
    )
