"""Add bounded crawl runs and page evidence snapshots.

Revision ID: 0068_seo_crawler
Revises: 0067_seo_site_metrics
Create Date: 2026-08-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0068_seo_crawler"
down_revision: Union[str, None] = "0067_seo_site_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "seo_crawl_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("seo_sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="running"),
        sa.Column("seed_url", sa.Text(), nullable=False),
        sa.Column("max_urls", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("discovered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fetched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("issue_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('running','completed','partial','failed')",
            name="ck_seo_crawl_run_status",
        ),
    )
    op.create_index("ix_seo_crawl_runs_tenant_id", "seo_crawl_runs", ["tenant_id"])
    op.create_index("ix_seo_crawl_runs_site_id", "seo_crawl_runs", ["site_id"])
    op.create_index("ix_seo_crawl_runs_status", "seo_crawl_runs", ["status"])
    op.create_index("ix_seo_crawl_runs_latest", "seo_crawl_runs", ["site_id", "started_at"])

    op.create_table(
        "seo_page_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("seo_sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("crawl_run_id", sa.BigInteger(), sa.ForeignKey("seo_crawl_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("discovery_source", sa.String(32), nullable=False, server_default="internal_link"),
        sa.Column("click_depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("redirect_chain", postgresql.JSONB(), nullable=True),
        sa.Column("fetch_error", sa.Text(), nullable=True),
        sa.Column("error_type", sa.String(40), nullable=True),
        sa.Column("content_type", sa.String(160), nullable=True),
        sa.Column("content_length", sa.Integer(), nullable=True),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("raw_html_hash", sa.String(64), nullable=True),
        sa.Column("robots_allowed", sa.Boolean(), nullable=True),
        sa.Column("meta_robots", sa.Text(), nullable=True),
        sa.Column("x_robots_tag", sa.Text(), nullable=True),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("indexable", sa.Boolean(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("title_length", sa.Integer(), nullable=True),
        sa.Column("meta_description", sa.Text(), nullable=True),
        sa.Column("description_length", sa.Integer(), nullable=True),
        sa.Column("h1_texts", postgresql.JSONB(), nullable=True),
        sa.Column("h1_count", sa.Integer(), nullable=True),
        sa.Column("html_lang", sa.String(40), nullable=True),
        sa.Column("main_content_extractable", sa.Boolean(), nullable=True),
        sa.Column("main_content_hash", sa.String(64), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column("schema_types", postgresql.JSONB(), nullable=True),
        sa.Column("schema_jsonld_count", sa.Integer(), nullable=True),
        sa.Column("schema_parse_error", sa.Boolean(), nullable=True),
        sa.Column("internal_links_count", sa.Integer(), nullable=True),
        sa.Column("external_links_count", sa.Integer(), nullable=True),
        sa.Column("images_count", sa.Integer(), nullable=True),
        sa.Column("images_missing_alt_count", sa.Integer(), nullable=True),
        sa.Column("hreflang_tags", postgresql.JSONB(), nullable=True),
        sa.Column("issue_codes", postgresql.JSONB(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("crawl_run_id", "url", name="uq_seo_page_snapshot_run_url"),
    )
    op.create_index("ix_seo_page_snapshots_tenant_id", "seo_page_snapshots", ["tenant_id"])
    op.create_index("ix_seo_page_snapshots_site_id", "seo_page_snapshots", ["site_id"])
    op.create_index("ix_seo_page_snapshots_crawl_run_id", "seo_page_snapshots", ["crawl_run_id"])
    op.create_index("ix_seo_page_snapshots_site_fetched", "seo_page_snapshots", ["site_id", "fetched_at"])


def downgrade() -> None:
    op.drop_table("seo_page_snapshots")
    op.drop_table("seo_crawl_runs")
