"""closed-loop: snapshot↔publication attribution, periods, task business_id

Revision ID: 0060_geo_closed_loop_attr
Revises: 0059_geo_alias_deliverable
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0060_geo_closed_loop_attr"
down_revision: Union[str, None] = "0059_geo_alias_deliverable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "geo_answer_snapshots",
        sa.Column(
            "matched_publication_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "geo_content_tasks",
        sa.Column("business_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "geo_content_tasks",
        sa.Column("review_submitted_by", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_geo_content_tasks_business_id",
        "geo_content_tasks",
        ["business_id"],
    )
    op.create_foreign_key(
        "fk_geo_content_tasks_business_id",
        "geo_content_tasks",
        "geo_optimization_businesses",
        ["business_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "geo_optimization_periods",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column(
            "business_id",
            sa.BigInteger(),
            sa.ForeignKey("geo_optimization_businesses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="planned"),
        sa.Column("goal_note", sa.Text(), nullable=True),
        sa.Column(
            "baseline_meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "result_meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "publication_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_geo_optimization_periods_tenant_id",
        "geo_optimization_periods",
        ["tenant_id"],
    )
    op.create_index(
        "ix_geo_optimization_periods_business_id",
        "geo_optimization_periods",
        ["business_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_geo_optimization_periods_business_id",
        table_name="geo_optimization_periods",
    )
    op.drop_index(
        "ix_geo_optimization_periods_tenant_id",
        table_name="geo_optimization_periods",
    )
    op.drop_table("geo_optimization_periods")
    op.drop_constraint(
        "fk_geo_content_tasks_business_id",
        "geo_content_tasks",
        type_="foreignkey",
    )
    op.drop_index("ix_geo_content_tasks_business_id", table_name="geo_content_tasks")
    op.drop_column("geo_content_tasks", "review_submitted_by")
    op.drop_column("geo_content_tasks", "business_id")
    op.drop_column("geo_answer_snapshots", "matched_publication_ids")
