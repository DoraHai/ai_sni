"""geo onboarding async jobs + monitoring stance

Revision ID: 0061_geo_onboard_async
Revises: 0060_geo_closed_loop_attr
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0061_geo_onboard_async"
down_revision: Union[str, None] = "0060_geo_closed_loop_attr"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geo_async_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("ref_type", sa.String(40), nullable=True),
        sa.Column("ref_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "request_meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "result_meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_geo_async_jobs_tenant_id", "geo_async_jobs", ["tenant_id"])
    op.create_index("ix_geo_async_jobs_ref_id", "geo_async_jobs", ["ref_id"])

    op.add_column(
        "geo_ai_settings",
        sa.Column(
            "monitoring_stance",
            sa.String(32),
            nullable=False,
            server_default="hybrid",
        ),
    )


def downgrade() -> None:
    op.drop_column("geo_ai_settings", "monitoring_stance")
    op.drop_index("ix_geo_async_jobs_ref_id", table_name="geo_async_jobs")
    op.drop_index("ix_geo_async_jobs_tenant_id", table_name="geo_async_jobs")
    op.drop_table("geo_async_jobs")
