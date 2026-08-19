"""Add tenant-scoped SEO distribution connections and publication records.

Revision ID: 0071_seo_distribution
Revises: 0070_seo_content_keywords
Create Date: 2026-08-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0071_seo_distribution"
down_revision: Union[str, None] = "0070_seo_content_keywords"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _attach_sequence(table: str) -> None:
    op.execute(sa.text(f"CREATE SEQUENCE IF NOT EXISTS {table}_id_seq"))
    op.execute(
        sa.text(f"ALTER TABLE {table} ALTER COLUMN id SET DEFAULT nextval('{table}_id_seq')")
    )
    op.execute(sa.text(f"ALTER SEQUENCE {table}_id_seq OWNED BY {table}.id"))


def upgrade() -> None:
    op.create_table(
        "seo_distribution_connections",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("platform_code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("mode", sa.String(24), nullable=False, server_default="manual"),
        sa.Column("base_url", sa.Text()),
        sa.Column("config", postgresql.JSONB()),
        sa.Column("capabilities", postgresql.JSONB()),
        sa.Column("credentials_encrypted", sa.Text()),
        sa.Column("has_credentials", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(24), nullable=False, server_default="unconfigured"),
        sa.Column("last_error", sa.Text()),
        sa.Column("last_tested_at", sa.DateTime()),
        sa.Column("created_by", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id", "name", name="uq_seo_distribution_connection_tenant_name"
        ),
    )
    op.create_index(
        "ix_seo_distribution_connections_tenant_id",
        "seo_distribution_connections",
        ["tenant_id"],
    )
    op.create_index(
        "ix_seo_distribution_connection_status",
        "seo_distribution_connections",
        ["tenant_id", "status", "enabled"],
    )

    op.create_table(
        "seo_content_publications",
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
            sa.ForeignKey("seo_distribution_connections.id", ondelete="SET NULL"),
        ),
        sa.Column("platform_code", sa.String(40), nullable=False),
        sa.Column("platform_name", sa.String(120), nullable=False),
        sa.Column("publish_mode", sa.String(24), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("source_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("adapted_title", sa.Text()),
        sa.Column("adapted_excerpt", sa.Text()),
        sa.Column("adapted_content", sa.Text()),
        sa.Column("external_id", sa.String(255)),
        sa.Column("page_url", sa.Text()),
        sa.Column("handoff_url", sa.Text()),
        sa.Column("idempotency_key", sa.String(64), unique=True),
        sa.Column("last_error", sa.Text()),
        sa.Column("published_at", sa.DateTime()),
        sa.Column("last_synced_at", sa.DateTime()),
        sa.Column("created_by", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id",
            "content_asset_id",
            "page_url",
            name="uq_seo_publication_asset_url",
        ),
    )
    op.create_index(
        "ix_seo_content_publications_tenant_id",
        "seo_content_publications",
        ["tenant_id"],
    )
    op.create_index(
        "ix_seo_content_publications_content_asset_id",
        "seo_content_publications",
        ["content_asset_id"],
    )
    op.create_index(
        "ix_seo_content_publications_connection_id",
        "seo_content_publications",
        ["connection_id"],
    )
    op.create_index(
        "ix_seo_publication_status",
        "seo_content_publications",
        ["tenant_id", "status", "updated_at"],
    )

    op.create_table(
        "seo_publish_attempts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "publication_id",
            sa.BigInteger(),
            sa.ForeignKey("seo_content_publications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("request_summary", postgresql.JSONB()),
        sa.Column("response_summary", postgresql.JSONB()),
        sa.Column("error", sa.Text()),
        sa.Column("created_by", sa.BigInteger()),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime()),
    )
    op.create_index(
        "ix_seo_publish_attempts_tenant_id",
        "seo_publish_attempts",
        ["tenant_id"],
    )
    op.create_index(
        "ix_seo_publish_attempts_publication_id",
        "seo_publish_attempts",
        ["publication_id"],
    )

    for table in (
        "seo_distribution_connections",
        "seo_content_publications",
        "seo_publish_attempts",
    ):
        _attach_sequence(table)

    op.execute(
        """
        INSERT INTO seo_content_publications (
            tenant_id,
            content_asset_id,
            platform_code,
            platform_name,
            publish_mode,
            status,
            source_version,
            page_url,
            published_at,
            created_by,
            created_at,
            updated_at
        )
        SELECT
            tenant_id,
            id,
            'legacy',
            LEFT(
                regexp_replace(page_url, '^https?://(www\\.)?([^/:?#]+).*$', '\\2'),
                120
            ),
            'manual',
            'published',
            COALESCE(version_count, 1),
            page_url,
            published_at,
            created_by,
            COALESCE(created_at, now()),
            COALESCE(updated_at, now())
        FROM seo_content_assets
        WHERE page_url IS NOT NULL AND btrim(page_url) <> ''
        """
    )


def downgrade() -> None:
    op.drop_index("ix_seo_publish_attempts_publication_id", table_name="seo_publish_attempts")
    op.drop_index("ix_seo_publish_attempts_tenant_id", table_name="seo_publish_attempts")
    op.drop_table("seo_publish_attempts")
    op.drop_index("ix_seo_publication_status", table_name="seo_content_publications")
    op.drop_index("ix_seo_content_publications_connection_id", table_name="seo_content_publications")
    op.drop_index("ix_seo_content_publications_content_asset_id", table_name="seo_content_publications")
    op.drop_index("ix_seo_content_publications_tenant_id", table_name="seo_content_publications")
    op.drop_table("seo_content_publications")
    op.drop_index("ix_seo_distribution_connection_status", table_name="seo_distribution_connections")
    op.drop_index("ix_seo_distribution_connections_tenant_id", table_name="seo_distribution_connections")
    op.drop_table("seo_distribution_connections")
