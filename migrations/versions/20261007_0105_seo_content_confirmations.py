"""Exact-version SEO content confirmations and advisor assignments.

This migration source has not been executed in any environment. Production
execution requires separate review and approval.

Revision ID: 0105_seo_content_confirmations
Revises: 0104_seo_page_ai_tdk
"""

from alembic import op
import sqlalchemy as sa


revision = "0105_seo_content_confirmations"
down_revision = "0104_seo_page_ai_tdk"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "seo_site_advisor_assignments",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("seo_sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("advisor_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("assigned_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id", "site_id", "advisor_user_id",
            name="uq_seo_site_advisor_assignment_scope_user",
        ),
    )
    op.create_index("ix_seo_site_advisor_assignments_tenant_id", "seo_site_advisor_assignments", ["tenant_id"])
    op.create_index("ix_seo_site_advisor_assignments_site_id", "seo_site_advisor_assignments", ["site_id"])
    op.create_index("ix_seo_site_advisor_assignments_advisor_user_id", "seo_site_advisor_assignments", ["advisor_user_id"])
    op.create_index(
        "ix_seo_site_advisor_assignment_scope_active",
        "seo_site_advisor_assignments", ["tenant_id", "site_id", "active"],
    )

    op.create_table(
        "seo_content_confirmations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("seo_sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content_asset_id", sa.BigInteger(), sa.ForeignKey("seo_content_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("actor_mode", sa.String(24), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_role_name", sa.String(50), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("content_version > 0", name="ck_seo_content_confirmation_version"),
        sa.CheckConstraint("decision IN ('approve','reject')", name="ck_seo_content_confirmation_decision"),
        sa.CheckConstraint(
            "actor_mode IN ('customer_direct','advisor_proxy')",
            name="ck_seo_content_confirmation_actor_mode",
        ),
    )
    op.create_index("ix_seo_content_confirmations_tenant_id", "seo_content_confirmations", ["tenant_id"])
    op.create_index("ix_seo_content_confirmations_site_id", "seo_content_confirmations", ["site_id"])
    op.create_index("ix_seo_content_confirmations_content_asset_id", "seo_content_confirmations", ["content_asset_id"])
    op.create_index(
        "ix_seo_content_confirmation_asset_latest",
        "seo_content_confirmations", ["tenant_id", "content_asset_id", "created_at", "id"],
    )
    op.create_index(
        "ix_seo_content_confirmation_exact_version",
        "seo_content_confirmations", ["content_asset_id", "content_version", "content_hash"],
    )


def downgrade():
    op.drop_index("ix_seo_content_confirmation_exact_version", table_name="seo_content_confirmations")
    op.drop_index("ix_seo_content_confirmation_asset_latest", table_name="seo_content_confirmations")
    op.drop_index("ix_seo_content_confirmations_content_asset_id", table_name="seo_content_confirmations")
    op.drop_index("ix_seo_content_confirmations_site_id", table_name="seo_content_confirmations")
    op.drop_index("ix_seo_content_confirmations_tenant_id", table_name="seo_content_confirmations")
    op.drop_table("seo_content_confirmations")

    op.drop_index("ix_seo_site_advisor_assignment_scope_active", table_name="seo_site_advisor_assignments")
    op.drop_index("ix_seo_site_advisor_assignments_advisor_user_id", table_name="seo_site_advisor_assignments")
    op.drop_index("ix_seo_site_advisor_assignments_site_id", table_name="seo_site_advisor_assignments")
    op.drop_index("ix_seo_site_advisor_assignments_tenant_id", table_name="seo_site_advisor_assignments")
    op.drop_table("seo_site_advisor_assignments")
