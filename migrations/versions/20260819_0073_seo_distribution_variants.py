"""Add versioned SEO platform-specific distribution drafts.

Revision ID: 0073_seo_distribution_variants
Revises: 0072_merge_login_seo
Create Date: 2026-08-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0073_seo_distribution_variants"
down_revision: Union[str, None] = "0072_merge_login_seo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "seo_distribution_variants",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "content_asset_id",
            sa.BigInteger(),
            sa.ForeignKey("seo_content_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "connection_id",
            sa.BigInteger(),
            sa.ForeignKey("seo_distribution_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform_code", sa.String(40), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("revision_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("excerpt", sa.Text()),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("keyword_checks", postgresql.JSONB()),
        sa.Column("warnings", postgresql.JSONB()),
        sa.Column("ai_generated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("generation_instruction", sa.Text()),
        sa.Column("feedback", sa.Text()),
        sa.Column("review_note", sa.Text()),
        sa.Column("reviewed_by", sa.BigInteger()),
        sa.Column("reviewed_at", sa.DateTime()),
        sa.Column("created_by", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id",
            "content_asset_id",
            "connection_id",
            "revision_number",
            name="uq_seo_distribution_variant_revision",
        ),
    )
    op.create_index(
        "ix_seo_distribution_variants_tenant_id",
        "seo_distribution_variants",
        ["tenant_id"],
    )
    op.create_index(
        "ix_seo_distribution_variants_content_asset_id",
        "seo_distribution_variants",
        ["content_asset_id"],
    )
    op.create_index(
        "ix_seo_distribution_variants_connection_id",
        "seo_distribution_variants",
        ["connection_id"],
    )
    op.create_index(
        "ix_seo_distribution_variant_latest",
        "seo_distribution_variants",
        ["tenant_id", "content_asset_id", "connection_id", "revision_number"],
    )
    op.create_index(
        "ix_seo_distribution_variant_status",
        "seo_distribution_variants",
        ["tenant_id", "status", "updated_at"],
    )
    op.execute(sa.text("CREATE SEQUENCE IF NOT EXISTS seo_distribution_variants_id_seq"))
    op.execute(
        sa.text(
            "ALTER TABLE seo_distribution_variants ALTER COLUMN id "
            "SET DEFAULT nextval('seo_distribution_variants_id_seq')"
        )
    )
    op.add_column(
        "seo_content_publications",
        sa.Column("variant_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_seo_content_publications_variant_id",
        "seo_content_publications",
        "seo_distribution_variants",
        ["variant_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_seo_content_publications_variant_id",
        "seo_content_publications",
        ["variant_id"],
    )
    op.execute(
        sa.text(
            "ALTER SEQUENCE seo_distribution_variants_id_seq "
            "OWNED BY seo_distribution_variants.id"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_seo_content_publications_variant_id", table_name="seo_content_publications")
    op.drop_constraint(
        "fk_seo_content_publications_variant_id",
        "seo_content_publications",
        type_="foreignkey",
    )
    op.drop_column("seo_content_publications", "variant_id")
    op.drop_index("ix_seo_distribution_variant_status", table_name="seo_distribution_variants")
    op.drop_index("ix_seo_distribution_variant_latest", table_name="seo_distribution_variants")
    op.drop_index("ix_seo_distribution_variants_connection_id", table_name="seo_distribution_variants")
    op.drop_index("ix_seo_distribution_variants_content_asset_id", table_name="seo_distribution_variants")
    op.drop_index("ix_seo_distribution_variants_tenant_id", table_name="seo_distribution_variants")
    op.drop_table("seo_distribution_variants")
