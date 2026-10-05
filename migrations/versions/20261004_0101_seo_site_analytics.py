"""Per-site analytics and publication export settings.

未在任何环境执行；生产执行前须单独审核。

Revision ID: 0101_seo_site_analytics
Revises: 0100_seo_page_captures
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0101_seo_site_analytics"
down_revision = "0100_seo_page_captures"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("seo_site_analytics_sources",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("seo_sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column("secret_ciphertext", sa.Text()),
        sa.Column("last_test_at", sa.DateTime(timezone=True)),
        sa.Column("last_test_status", sa.String(16)),
        sa.Column("last_test_message", sa.Text()),
        sa.Column("token_expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.BigInteger()), sa.Column("updated_by", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("site_id", "source"),
        sa.CheckConstraint("source IN ('baidu_tongji','ga4')"))
    op.create_table("seo_site_analytics_monthly",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("seo_sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(24), nullable=False), sa.Column("month", sa.String(7), nullable=False),
        sa.Column("uv", sa.BigInteger()), sa.Column("pv", sa.BigInteger()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(48)), sa.Column("error_message", sa.Text()),
        sa.Column("fetched_at", sa.DateTime(timezone=True)), sa.Column("fetched_by", sa.BigInteger()),
        sa.Column("raw_meta", JSONB(), nullable=False),
        sa.Column("last_error_code", sa.String(48)), sa.Column("last_error_message", sa.Text()),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("site_id", "source", "month"),
        sa.CheckConstraint("status IN ('ok','no_data','failed')"))
    op.create_table("seo_site_export_templates",
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("seo_sites.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("columns", JSONB(), nullable=False), sa.Column("updated_by", sa.BigInteger()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()))


def downgrade():
    op.drop_table("seo_site_export_templates")
    op.drop_table("seo_site_analytics_monthly")
    op.drop_table("seo_site_analytics_sources")
