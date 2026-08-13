"""period_id on snapshots/tasks/pubs + backfill sample_mode/simulated from note

Revision ID: 0062_geo_metric_period
Revises: 0061_geo_onboard_async
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0062_geo_metric_period"
down_revision: Union[str, None] = "0061_geo_onboard_async"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # period linkage (W2)
    op.add_column(
        "geo_answer_snapshots",
        sa.Column("period_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_geo_answer_snapshots_period_id",
        "geo_answer_snapshots",
        ["period_id"],
    )
    op.create_foreign_key(
        "fk_geo_answer_snapshots_period_id",
        "geo_answer_snapshots",
        "geo_optimization_periods",
        ["period_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "geo_content_tasks",
        sa.Column("period_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_geo_content_tasks_period_id", "geo_content_tasks", ["period_id"]
    )
    op.create_foreign_key(
        "fk_geo_content_tasks_period_id",
        "geo_content_tasks",
        "geo_optimization_periods",
        ["period_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "geo_publications",
        sa.Column("period_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "geo_publications",
        sa.Column("canonical_url", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_geo_publications_period_id", "geo_publications", ["period_id"]
    )
    op.create_foreign_key(
        "fk_geo_publications_period_id",
        "geo_publications",
        "geo_optimization_periods",
        ["period_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Backfill sample_mode / simulated from note (never invent true without evidence)
    # unknown mode when cannot infer — leave sample_mode as-is if already non-default
    conn = op.get_bind()
    # mark simulated when note clearly says so
    conn.execute(
        sa.text(
            """
            UPDATE geo_answer_snapshots
            SET simulated = true,
                sample_mode = CASE
                  WHEN sample_mode IS NULL OR sample_mode IN ('manual', '') THEN 'mock_persona'
                  ELSE sample_mode
                END
            WHERE simulated = false
              AND (
                note ILIKE '%模拟%'
                OR note ILIKE '%mock_persona%'
                OR sample_mode = 'mock_persona'
              )
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE geo_answer_snapshots
            SET sample_mode = 'openai_compat',
                simulated = false
            WHERE (note ILIKE '%真采样%' OR note ILIKE '%openai_compat%')
              AND note NOT ILIKE '%模拟%'
            """
        )
    )
    # remaining legacy patrol notes without clear signal → sample_mode unknown
    conn.execute(
        sa.text(
            """
            UPDATE geo_answer_snapshots
            SET sample_mode = 'unknown'
            WHERE (sample_mode IS NULL OR sample_mode = 'manual')
              AND note IS NOT NULL
              AND note ILIKE '%auto-patrol%'
              AND note NOT ILIKE '%模拟%'
              AND note NOT ILIKE '%真采样%'
              AND note NOT ILIKE '%mock_persona%'
              AND note NOT ILIKE '%openai_compat%'
            """
        )
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_geo_publications_period_id", "geo_publications", type_="foreignkey"
    )
    op.drop_index("ix_geo_publications_period_id", table_name="geo_publications")
    op.drop_column("geo_publications", "canonical_url")
    op.drop_column("geo_publications", "period_id")

    op.drop_constraint(
        "fk_geo_content_tasks_period_id", "geo_content_tasks", type_="foreignkey"
    )
    op.drop_index("ix_geo_content_tasks_period_id", table_name="geo_content_tasks")
    op.drop_column("geo_content_tasks", "period_id")

    op.drop_constraint(
        "fk_geo_answer_snapshots_period_id",
        "geo_answer_snapshots",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_geo_answer_snapshots_period_id", table_name="geo_answer_snapshots"
    )
    op.drop_column("geo_answer_snapshots", "period_id")
