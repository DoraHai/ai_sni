"""GEO Wave B2: tracking engines + media placements

Revision ID: 0039_geo_wave_b2
Revises: 0038_geo_wave_b_visibility
Create Date: 2026-07-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0039_geo_wave_b2"
down_revision: Union[str, None] = "0038_geo_wave_b_visibility"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geo_tracking_engines",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("engine_key", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "engine_key", name="uq_geo_tracking_engines_tenant_key"),
    )
    op.create_index(
        "ix_geo_tracking_engines_tenant_id", "geo_tracking_engines", ["tenant_id"]
    )

    op.create_table(
        "geo_media_placements",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("channel_type", sa.String(length=32), nullable=False, server_default="other"),
        sa.Column("target_url", sa.Text(), nullable=True),
        sa.Column("authority_note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="planned"),
        sa.Column("published_url", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "related_prompt_id",
            sa.BigInteger(),
            sa.ForeignKey("geo_prompts.id"),
            nullable=True,
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_geo_media_placements_tenant_id", "geo_media_placements", ["tenant_id"]
    )
    op.create_index(
        "ix_geo_media_placements_tenant_status",
        "geo_media_placements",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_geo_media_placements_tenant_status", table_name="geo_media_placements"
    )
    op.drop_index("ix_geo_media_placements_tenant_id", table_name="geo_media_placements")
    op.drop_table("geo_media_placements")
    op.drop_index("ix_geo_tracking_engines_tenant_id", table_name="geo_tracking_engines")
    op.drop_table("geo_tracking_engines")
