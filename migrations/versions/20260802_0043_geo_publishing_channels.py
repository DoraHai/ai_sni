"""GEO publishing channels and account settings.

Revision ID: 0043_geo_publishing_channels
Revises: 0042_geo_ai_settings
Create Date: 2026-08-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0043_geo_publishing_channels"
down_revision: Union[str, None] = "0042_geo_ai_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geo_publishing_channels",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("channel_type", sa.String(length=32), nullable=False),
        sa.Column("publish_mode", sa.String(length=32), nullable=False, server_default="manual_only"),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("content_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_geo_publishing_channels_tenant_name"),
    )
    op.create_index("ix_geo_publishing_channels_tenant_id", "geo_publishing_channels", ["tenant_id"])
    op.create_table(
        "geo_channel_accounts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), sa.ForeignKey("geo_publishing_channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("auth_type", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("credentials_encrypted", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="unconfigured"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("channel_id", "display_name", name="uq_geo_channel_accounts_channel_name"),
    )
    op.create_index("ix_geo_channel_accounts_tenant_id", "geo_channel_accounts", ["tenant_id"])
    op.create_index("ix_geo_channel_accounts_channel_id", "geo_channel_accounts", ["channel_id"])


def downgrade() -> None:
    op.drop_index("ix_geo_channel_accounts_channel_id", table_name="geo_channel_accounts")
    op.drop_index("ix_geo_channel_accounts_tenant_id", table_name="geo_channel_accounts")
    op.drop_table("geo_channel_accounts")
    op.drop_index("ix_geo_publishing_channels_tenant_id", table_name="geo_publishing_channels")
    op.drop_table("geo_publishing_channels")
