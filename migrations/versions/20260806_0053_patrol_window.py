"""GEO visibility patrol schedule window + interval.

Revision ID: 0053_patrol_window
Revises: 0052_geo_vis_patrol
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0053_patrol_window"
down_revision = "0052_geo_vis_patrol"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "geo_visibility_patrol_settings",
        sa.Column("window_start_hour", sa.Integer(), nullable=False, server_default="6"),
    )
    op.add_column(
        "geo_visibility_patrol_settings",
        sa.Column("window_end_hour", sa.Integer(), nullable=False, server_default="22"),
    )
    op.add_column(
        "geo_visibility_patrol_settings",
        sa.Column("interval_hours", sa.Integer(), nullable=False, server_default="24"),
    )
    op.add_column(
        "geo_visibility_patrol_settings",
        sa.Column("last_scheduled_at", sa.DateTime(), nullable=True),
    )
    # backfill: single-hour legacy daily_hour → window collapsed to that hour, daily interval
    op.execute(
        """
        UPDATE geo_visibility_patrol_settings
        SET window_start_hour = daily_hour,
            window_end_hour = daily_hour,
            interval_hours = 24
        """
    )


def downgrade() -> None:
    op.drop_column("geo_visibility_patrol_settings", "last_scheduled_at")
    op.drop_column("geo_visibility_patrol_settings", "interval_hours")
    op.drop_column("geo_visibility_patrol_settings", "window_end_hour")
    op.drop_column("geo_visibility_patrol_settings", "window_start_hour")
