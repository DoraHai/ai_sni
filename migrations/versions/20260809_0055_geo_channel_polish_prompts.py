"""GEO channel polish prompts (tenant overrides).

Revision ID: 0055_geo_channel_polish_prompts
Revises: 0054_geo_opt_hierarchy
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0055_geo_channel_polish_prompts"
down_revision: Union[str, None] = "0054_geo_opt_hierarchy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geo_channel_polish_prompts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("channel_key", sa.String(length=32), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("voice_prompt", sa.Text(), nullable=True),
        sa.Column("min_body_chars", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "channel_key", name="uq_geo_channel_polish_prompts"),
    )
    op.create_index(
        "ix_geo_channel_polish_prompts_tenant_id",
        "geo_channel_polish_prompts",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_geo_channel_polish_prompts_tenant_id",
        table_name="geo_channel_polish_prompts",
    )
    op.drop_table("geo_channel_polish_prompts")
