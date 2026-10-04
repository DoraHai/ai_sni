"""SEO page capture evidence.

未在任何环境执行；生产执行前须单独审核。

Revision ID: 0100_seo_page_captures
Revises: 0099_geo_review_audit
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0100_seo_page_captures"
down_revision = "0099_geo_review_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seo_page_captures",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("seo_sites.id"), nullable=False),
        sa.Column("relation_type", sa.String(24), nullable=False),
        sa.Column("relation_id", sa.BigInteger(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text()),
        sa.Column("http_status", sa.Integer()),
        sa.Column("redirect_chain", JSONB(), nullable=False),
        sa.Column("warnings", JSONB(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(40)),
        sa.Column("viewport_width", sa.Integer(), nullable=False),
        sa.Column("viewport_height", sa.Integer(), nullable=False),
        sa.Column("image_width", sa.Integer()),
        sa.Column("image_height", sa.Integer()),
        sa.Column("sha256", sa.String(64)),
        sa.Column("storage_key", sa.String(120)),
        sa.CheckConstraint("status IN ('pending', 'running', 'succeeded', 'failed')", name="ck_seo_page_captures_status"),
    )
    op.create_index("ix_seo_page_captures_scope", "seo_page_captures", ["tenant_id", "site_id", "relation_type", "relation_id"])
    op.create_index("ix_seo_page_captures_timeline", "seo_page_captures", ["tenant_id", "site_id", "captured_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_seo_page_captures_timeline", table_name="seo_page_captures")
    op.drop_index("ix_seo_page_captures_scope", table_name="seo_page_captures")
    op.drop_table("seo_page_captures")
