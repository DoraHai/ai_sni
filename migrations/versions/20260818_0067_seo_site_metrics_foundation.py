"""Add site ownership and metric snapshots to the SEO data layer.

Revision ID: 0067_seo_site_metrics
Revises: 0066_module_workspaces
Create Date: 2026-08-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0067_seo_site_metrics"
down_revision: Union[str, None] = "0066_module_workspaces"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEO_TABLES = (
    "seo_keyword_assets",
    "seo_rank_snapshots",
    "seo_brand_assets",
    "seo_serp_results",
    "seo_site_pages",
    "seo_content_assets",
    "seo_internal_links",
    "seo_backlinks",
    "seo_competitors",
    "seo_competitor_events",
)

OLD_UNIQUES = {
    "seo_keyword_assets": "uq_seo_keyword_tenant_word",
    "seo_brand_assets": "uq_seo_brand_asset_match",
    "seo_site_pages": "uq_seo_site_page_tenant_url",
    "seo_internal_links": "uq_seo_internal_link_edge",
    "seo_backlinks": "uq_seo_backlink_source_target",
    "seo_competitors": "uq_seo_competitor_domain",
    "seo_competitor_events": "uq_seo_competitor_event",
}


def upgrade() -> None:
    for table in SEO_TABLES:
        op.add_column(table, sa.Column("site_id", sa.BigInteger(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_site_id",
            table,
            "seo_sites",
            ["site_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(f"ix_{table}_site_id", table, ["site_id"])

    # Existing data can be assigned safely only when a tenant has exactly one site.
    for table in SEO_TABLES:
        op.execute(
            sa.text(
                f"""
                UPDATE {table} AS target
                SET site_id = sites.id
                FROM (
                    SELECT tenant_id, min(id) AS id
                    FROM seo_sites
                    GROUP BY tenant_id
                    HAVING count(*) = 1
                ) AS sites
                WHERE target.tenant_id = sites.tenant_id
                  AND target.site_id IS NULL
                """
            )
        )

    for table, constraint in OLD_UNIQUES.items():
        op.drop_constraint(constraint, table, type_="unique")

    op.create_unique_constraint(
        "uq_seo_keyword_site_word",
        "seo_keyword_assets",
        ["tenant_id", "site_id", "keyword"],
    )
    op.create_unique_constraint(
        "uq_seo_brand_asset_site_match",
        "seo_brand_assets",
        ["tenant_id", "site_id", "asset_type", "match_value"],
    )
    op.create_unique_constraint(
        "uq_seo_site_page_site_url",
        "seo_site_pages",
        ["tenant_id", "site_id", "url"],
    )
    op.create_unique_constraint(
        "uq_seo_internal_link_site_edge",
        "seo_internal_links",
        ["tenant_id", "site_id", "source_page_id", "target_page_id", "anchor_text"],
    )
    op.create_unique_constraint(
        "uq_seo_backlink_site_source_target",
        "seo_backlinks",
        ["tenant_id", "site_id", "source_url", "target_url"],
    )
    op.create_unique_constraint(
        "uq_seo_competitor_site_domain",
        "seo_competitors",
        ["tenant_id", "site_id", "domain"],
    )
    op.create_unique_constraint(
        "uq_seo_competitor_site_event",
        "seo_competitor_events",
        ["tenant_id", "site_id", "competitor_id", "event_type", "url"],
    )

    op.create_table(
        "seo_metric_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("seo_sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_type", sa.String(64), nullable=False),
        sa.Column("dimension", sa.String(80), nullable=False, server_default="total"),
        sa.Column("numeric_value", sa.Numeric(20, 4), nullable=True),
        sa.Column("text_value", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(24), nullable=True),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("data_quality", sa.String(24), nullable=False, server_default="estimated"),
        sa.Column("status", sa.String(24), nullable=False, server_default="available"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("collected_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('available','not_configured','pending','failed','stale')",
            name="ck_seo_metric_snapshot_status",
        ),
        sa.CheckConstraint(
            "data_quality IN ('verified','estimated','crawled','imported')",
            name="ck_seo_metric_snapshot_quality",
        ),
        sa.UniqueConstraint(
            "site_id",
            "metric_type",
            "dimension",
            "source",
            "observed_at",
            name="uq_seo_metric_snapshot_observation",
        ),
    )
    op.create_index("ix_seo_metric_snapshots_tenant_id", "seo_metric_snapshots", ["tenant_id"])
    op.create_index("ix_seo_metric_snapshots_site_id", "seo_metric_snapshots", ["site_id"])
    op.create_index("ix_seo_metric_snapshots_metric_type", "seo_metric_snapshots", ["metric_type"])
    op.create_index("ix_seo_metric_snapshots_status", "seo_metric_snapshots", ["status"])
    op.create_index(
        "ix_seo_metric_snapshots_latest",
        "seo_metric_snapshots",
        ["site_id", "metric_type", "dimension", "observed_at"],
    )


def downgrade() -> None:
    op.drop_table("seo_metric_snapshots")

    new_uniques = {
        "seo_keyword_assets": "uq_seo_keyword_site_word",
        "seo_brand_assets": "uq_seo_brand_asset_site_match",
        "seo_site_pages": "uq_seo_site_page_site_url",
        "seo_internal_links": "uq_seo_internal_link_site_edge",
        "seo_backlinks": "uq_seo_backlink_site_source_target",
        "seo_competitors": "uq_seo_competitor_site_domain",
        "seo_competitor_events": "uq_seo_competitor_site_event",
    }
    for table, constraint in new_uniques.items():
        op.drop_constraint(constraint, table, type_="unique")

    op.create_unique_constraint("uq_seo_keyword_tenant_word", "seo_keyword_assets", ["tenant_id", "keyword"])
    op.create_unique_constraint("uq_seo_brand_asset_match", "seo_brand_assets", ["tenant_id", "asset_type", "match_value"])
    op.create_unique_constraint("uq_seo_site_page_tenant_url", "seo_site_pages", ["tenant_id", "url"])
    op.create_unique_constraint("uq_seo_internal_link_edge", "seo_internal_links", ["tenant_id", "source_page_id", "target_page_id", "anchor_text"])
    op.create_unique_constraint("uq_seo_backlink_source_target", "seo_backlinks", ["tenant_id", "source_url", "target_url"])
    op.create_unique_constraint("uq_seo_competitor_domain", "seo_competitors", ["tenant_id", "domain"])
    op.create_unique_constraint("uq_seo_competitor_event", "seo_competitor_events", ["tenant_id", "competitor_id", "event_type", "url"])

    for table in reversed(SEO_TABLES):
        op.drop_index(f"ix_{table}_site_id", table_name=table)
        op.drop_constraint(f"fk_{table}_site_id", table, type_="foreignkey")
        op.drop_column(table, "site_id")
