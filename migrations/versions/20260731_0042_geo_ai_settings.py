"""GEO AI capability settings (DashScope / DeepSeek)

Revision ID: 0042_geo_ai_settings
Revises: 0041_geo_wave_c
Create Date: 2026-07-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0042_geo_ai_settings"
down_revision: Union[str, None] = "0041_geo_wave_c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geo_ai_settings",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="dashscope"),
        sa.Column("base_url", sa.String(length=300), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", name="uq_geo_ai_settings_tenant"),
    )
    op.create_index("ix_geo_ai_settings_tenant_id", "geo_ai_settings", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_geo_ai_settings_tenant_id", table_name="geo_ai_settings")
    op.drop_table("geo_ai_settings")
