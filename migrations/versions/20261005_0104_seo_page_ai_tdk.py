"""Historical AI TDK suggestions.

未在任何环境执行；生产执行前须单独审核。

Revision ID: 0104_seo_page_ai_tdk
Revises: 0103_seo_tdk_review
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0104_seo_page_ai_tdk"
down_revision = "0103_seo_tdk_review"
branch_labels = None
depends_on = None


def upgrade():
    columns = [
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("seo_sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_id", sa.BigInteger(), sa.ForeignKey("seo_site_pages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("batch_id", sa.String(36), nullable=False),
        sa.Column("model_name", sa.String(120), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
    ]
    for field in ("title", "description", "keywords"):
        columns += [sa.Column(f"{field}_ai_value", sa.Text()), sa.Column(f"{field}_final_value", sa.Text()),
                    sa.Column(f"{field}_status", sa.String(16), nullable=False, server_default="ai_draft"),
                    sa.Column(f"{field}_reviewed_by", sa.BigInteger()),
                    sa.Column(f"{field}_reviewed_at", sa.DateTime(timezone=True)),
                    sa.CheckConstraint(f"{field}_status IN ('ai_draft','confirmed','modified','rejected')", name=f"ck_seo_page_ai_tdk_{field}_status")]
    columns += [
        sa.Column("reviewed_by", sa.BigInteger()), sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("reason", sa.Text()),
        sa.Column("internal_link_suggestions", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("warnings", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("dropped_links", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("raw_response_excerpt", sa.Text()), sa.Column("error_code", sa.String(40)),
        sa.Column("error_message", sa.Text()), sa.Column("created_by", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]
    op.create_table("seo_page_ai_tdk_suggestions", *columns)
    op.create_index("ix_seo_page_ai_tdk_scope_latest", "seo_page_ai_tdk_suggestions", ["tenant_id", "site_id", "page_id", "id"])


def downgrade():
    op.drop_index("ix_seo_page_ai_tdk_scope_latest", table_name="seo_page_ai_tdk_suggestions")
    op.drop_table("seo_page_ai_tdk_suggestions")
