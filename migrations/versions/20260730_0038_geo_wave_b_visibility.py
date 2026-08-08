"""GEO Wave B: answer snapshots for manual visibility tracking

Revision ID: 0038_geo_wave_b_visibility
Revises: 0037_geo_wave_a
Create Date: 2026-07-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038_geo_wave_b_visibility"
down_revision: Union[str, None] = "0037_geo_wave_a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geo_answer_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "prompt_id", sa.BigInteger(), sa.ForeignKey("geo_prompts.id"), nullable=False
        ),
        sa.Column("engine", sa.String(length=32), nullable=False, server_default="other"),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column(
            "mentions_brand", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("cited_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_geo_answer_snapshots_tenant_id", "geo_answer_snapshots", ["tenant_id"]
    )
    op.create_index(
        "ix_geo_answer_snapshots_prompt_id", "geo_answer_snapshots", ["prompt_id"]
    )
    op.create_index(
        "ix_geo_answer_snapshots_tenant_prompt",
        "geo_answer_snapshots",
        ["tenant_id", "prompt_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_geo_answer_snapshots_tenant_prompt", table_name="geo_answer_snapshots"
    )
    op.drop_index("ix_geo_answer_snapshots_prompt_id", table_name="geo_answer_snapshots")
    op.drop_index("ix_geo_answer_snapshots_tenant_id", table_name="geo_answer_snapshots")
    op.drop_table("geo_answer_snapshots")
