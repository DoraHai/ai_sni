"""geo answer snapshots: patrol_run_id + sample_mode + simulated

Revision ID: 0058_geo_snapshot_patrol_sample
Revises: 0057_geo_daily_comp_mentions
Create Date: 2026-08-11
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0058_geo_snapshot_patrol_sample"
down_revision: Union[str, None] = "0057_geo_daily_comp_mentions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "geo_answer_snapshots",
        sa.Column("patrol_run_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "geo_answer_snapshots",
        sa.Column(
            "sample_mode",
            sa.String(length=32),
            nullable=False,
            server_default="manual",
        ),
    )
    op.add_column(
        "geo_answer_snapshots",
        sa.Column(
            "simulated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_geo_answer_snapshots_patrol_run_id",
        "geo_answer_snapshots",
        ["patrol_run_id"],
    )
    op.create_index(
        "ix_geo_answer_snapshots_sample_mode",
        "geo_answer_snapshots",
        ["sample_mode"],
    )
    op.create_foreign_key(
        "fk_geo_answer_snapshots_patrol_run_id",
        "geo_answer_snapshots",
        "geo_visibility_patrol_runs",
        ["patrol_run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_geo_answer_snapshots_patrol_run_id",
        "geo_answer_snapshots",
        type_="foreignkey",
    )
    op.drop_index("ix_geo_answer_snapshots_sample_mode", table_name="geo_answer_snapshots")
    op.drop_index("ix_geo_answer_snapshots_patrol_run_id", table_name="geo_answer_snapshots")
    op.drop_column("geo_answer_snapshots", "simulated")
    op.drop_column("geo_answer_snapshots", "sample_mode")
    op.drop_column("geo_answer_snapshots", "patrol_run_id")
