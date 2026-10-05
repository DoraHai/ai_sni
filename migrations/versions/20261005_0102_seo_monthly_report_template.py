"""Per-site SEO monthly PDF report sections.

未在任何环境执行；生产执行前须单独审核。

Revision ID: 0102_seo_monthly_report_template
Revises: 0101_seo_site_analytics
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0102_seo_monthly_report_template"
down_revision = "0101_seo_site_analytics"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("seo_site_report_templates",
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("seo_sites.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sections", JSONB(), nullable=False),
        sa.Column("updated_by", sa.BigInteger()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()))


def downgrade():
    op.drop_table("seo_site_report_templates")
