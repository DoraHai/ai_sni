"""Persist SEO manual rank quota and in-flight reservations.

Revision ID: 0075_seo_rank_quota_state
Revises: 0074_merge_geo_seo_heads
Create Date: 2026-08-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0075_seo_rank_quota_state"
down_revision: Union[str, None] = "0074_merge_geo_seo_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "seo_manual_rank_limits",
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "site_id",
            sa.BigInteger(),
            sa.ForeignKey("seo_sites.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("daily_date", sa.Date(), nullable=False),
        sa.Column("daily_requests", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("reservation_token", sa.String(length=36), nullable=True),
        sa.Column("reserved_requests", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reservation_expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "daily_requests >= 0",
            name="ck_seo_manual_rank_daily_nonnegative",
        ),
        sa.CheckConstraint(
            "reserved_requests >= 0",
            name="ck_seo_manual_rank_reserved_nonnegative",
        ),
    )


def downgrade() -> None:
    op.drop_table("seo_manual_rank_limits")
