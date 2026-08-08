"""SEO keyword assets and onsite optimization foundation.

Revision ID: 0056_seo_foundation
Revises: 0055_merge_geo_platform
Create Date: 2026-08-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0056_seo_foundation"
down_revision: Union[str, None] = "0055_merge_geo_platform"
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
        "seo_keyword_assets",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("keyword", sa.Text(), nullable=False),
        sa.Column("cluster", sa.String(120)),
        sa.Column("intent", sa.String(24)),
        sa.Column("monthly_volume", sa.BigInteger()),
        sa.Column("difficulty", sa.SmallInteger()),
        sa.Column("priority", sa.String(4), nullable=False, server_default="P2"),
        sa.Column("landing_page", sa.Text()),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("notes", sa.Text()),
        sa.Column("created_by", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "keyword", name="uq_seo_keyword_tenant_word"),
    )
    op.create_index("ix_seo_keyword_assets_tenant_id", "seo_keyword_assets", ["tenant_id"])
    op.create_index(
        "ix_seo_keyword_assets_tenant_status",
        "seo_keyword_assets",
        ["tenant_id", "status"],
    )

    op.create_table(
        "seo_rank_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "keyword_id",
            sa.BigInteger(),
            sa.ForeignKey("seo_keyword_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("engine", sa.String(20), nullable=False),
        sa.Column("device", sa.String(16), nullable=False, server_default="desktop"),
        sa.Column("region", sa.String(80), nullable=False, server_default="全国"),
        sa.Column("domain", sa.String(255)),
        sa.Column("subject_type", sa.String(16), nullable=False, server_default="own"),
        sa.Column("rank", sa.SmallInteger()),
        sa.Column("result_url", sa.Text()),
        sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_seo_rank_snapshots_tenant_id", "seo_rank_snapshots", ["tenant_id"])
    op.create_index("ix_seo_rank_snapshots_keyword_id", "seo_rank_snapshots", ["keyword_id"])
    op.create_index(
        "ix_seo_rank_lookup",
        "seo_rank_snapshots",
        ["tenant_id", "keyword_id", "engine", "subject_type", "checked_at"],
    )

    op.create_table(
        "seo_site_pages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("page_type", sa.String(32)),
        sa.Column(
            "target_keyword_id",
            sa.BigInteger(),
            sa.ForeignKey("seo_keyword_assets.id", ondelete="SET NULL"),
        ),
        sa.Column("title", sa.Text()),
        sa.Column("meta_description", sa.Text()),
        sa.Column("meta_keywords", sa.Text()),
        sa.Column("h1", sa.Text()),
        sa.Column("canonical", sa.Text()),
        sa.Column("indexable", sa.Boolean()),
        sa.Column("http_status", sa.Integer()),
        sa.Column("content_units", sa.Integer()),
        sa.Column("audit_score", sa.SmallInteger()),
        sa.Column("issue_codes", postgresql.JSONB()),
        sa.Column("title_suggestion", sa.Text()),
        sa.Column("description_suggestion", sa.Text()),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("last_error", sa.Text()),
        sa.Column("last_checked_at", sa.DateTime()),
        sa.Column("created_by", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "url", name="uq_seo_site_page_tenant_url"),
    )
    op.create_index("ix_seo_site_pages_tenant_id", "seo_site_pages", ["tenant_id"])
    op.create_index(
        "ix_seo_site_pages_tenant_status", "seo_site_pages", ["tenant_id", "status"]
    )

    for table in ("seo_keyword_assets", "seo_rank_snapshots", "seo_site_pages"):
        _attach_sequence(table)

    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE roles SET permissions = permissions || "
            "'{\"seo.keywords\":\"edit\",\"seo.site\":\"edit\"}'::jsonb "
            "WHERE name IN ('管理员','运营')"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE roles SET permissions = permissions || "
            "'{\"seo.keywords\":\"view\",\"seo.site\":\"view\"}'::jsonb "
            "WHERE name = '品牌方客户'"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE roles SET permissions = permissions - 'seo.keywords' - 'seo.site'"
        )
    )
    op.drop_index("ix_seo_site_pages_tenant_status", table_name="seo_site_pages")
    op.drop_index("ix_seo_site_pages_tenant_id", table_name="seo_site_pages")
    op.drop_table("seo_site_pages")
    op.drop_index("ix_seo_rank_lookup", table_name="seo_rank_snapshots")
    op.drop_index("ix_seo_rank_snapshots_keyword_id", table_name="seo_rank_snapshots")
    op.drop_index("ix_seo_rank_snapshots_tenant_id", table_name="seo_rank_snapshots")
    op.drop_table("seo_rank_snapshots")
    op.drop_index("ix_seo_keyword_assets_tenant_status", table_name="seo_keyword_assets")
    op.drop_index("ix_seo_keyword_assets_tenant_id", table_name="seo_keyword_assets")
    op.drop_table("seo_keyword_assets")
