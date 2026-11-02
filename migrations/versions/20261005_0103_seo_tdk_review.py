"""TDK review draft exports.

未在任何环境执行；生产执行前须单独审核。

Revision ID: 0103_seo_tdk_review
Revises: 0102_seo_monthly_report_template
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0103_seo_tdk_review"
down_revision = "0102_seo_monthly_report_template"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("seo_tdk_review_batches",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("seo_sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_ids", JSONB(), nullable=False),
        sa.Column("created_by", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.Text()))
    op.create_index("ix_seo_tdk_review_batches_scope", "seo_tdk_review_batches", ["tenant_id", "site_id", "created_at"])
    op.create_table("seo_site_tdk_review_templates",
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("seo_sites.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sections", JSONB(), nullable=False),
        sa.Column("columns", JSONB(), nullable=False),
        sa.Column("updated_by", sa.BigInteger()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()))


def downgrade():
    op.drop_table("seo_site_tdk_review_templates")
    op.drop_index("ix_seo_tdk_review_batches_scope", table_name="seo_tdk_review_batches")
    op.drop_table("seo_tdk_review_batches")
