"""GEO Wave A: pipeline fields, import batch, diagnosis bridge

Revision ID: 0037_geo_wave_a
Revises: 0036_geo_content_workbench
Create Date: 2026-07-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0037_geo_wave_a"
down_revision: Union[str, None] = "0036_geo_content_workbench"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("geo_prompts", sa.Column("owner_user_id", sa.BigInteger(), nullable=True))
    op.add_column("geo_prompts", sa.Column("last_task_id", sa.BigInteger(), nullable=True))

    op.add_column("geo_facts", sa.Column("author_name", sa.String(length=100), nullable=True))
    op.add_column("geo_facts", sa.Column("import_batch_id", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_geo_facts_import_batch", "geo_facts", ["tenant_id", "import_batch_id"]
    )

    op.add_column(
        "geo_content_tasks",
        sa.Column("pipeline_step", sa.String(length=32), server_default="opportunity"),
    )
    op.add_column("geo_content_tasks", sa.Column("blocked_reason", sa.Text(), nullable=True))
    op.add_column(
        "geo_content_tasks", sa.Column("diagnosis_audit_id", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "geo_content_tasks",
        sa.Column("diagnosis_advice_code", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_geo_content_tasks_pipeline",
        "geo_content_tasks",
        ["tenant_id", "pipeline_step"],
    )

    op.add_column(
        "geo_article_versions", sa.Column("author_name", sa.String(length=100), nullable=True)
    )

    # backfill pipeline_step from existing status
    op.execute(
        sa.text(
            """
            UPDATE geo_content_tasks SET pipeline_step = CASE
              WHEN status = 'published' THEN 'publish'
              WHEN status IN ('exported', 'ready') THEN 'adapt'
              WHEN status IN ('editing', 'needs_fix', 'generating', 'failed') THEN 'draft'
              WHEN status = 'facts_bound' THEN 'evidence'
              ELSE 'opportunity'
            END
            WHERE pipeline_step IS NULL OR pipeline_step = 'opportunity'
            """
        )
    )


def downgrade() -> None:
    op.drop_column("geo_article_versions", "author_name")
    op.drop_index("ix_geo_content_tasks_pipeline", table_name="geo_content_tasks")
    op.drop_column("geo_content_tasks", "diagnosis_advice_code")
    op.drop_column("geo_content_tasks", "diagnosis_audit_id")
    op.drop_column("geo_content_tasks", "blocked_reason")
    op.drop_column("geo_content_tasks", "pipeline_step")
    op.drop_index("ix_geo_facts_import_batch", table_name="geo_facts")
    op.drop_column("geo_facts", "import_batch_id")
    op.drop_column("geo_facts", "author_name")
    op.drop_column("geo_prompts", "last_task_id")
    op.drop_column("geo_prompts", "owner_user_id")
