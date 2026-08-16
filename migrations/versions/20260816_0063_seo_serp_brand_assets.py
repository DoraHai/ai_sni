"""SEO SERP results and brand ownership assets.

Revision ID: 0063_seo_serp_brand_assets
Revises: 0062_campaign_geo_status
Create Date: 2026-08-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0063_seo_serp_brand_assets"
down_revision: Union[str, None] = "0062_campaign_geo_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "seo_brand_assets",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("asset_type", sa.String(24), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("match_value", sa.Text(), nullable=False),
        sa.Column("platform", sa.String(40)),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_by", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "asset_type", "match_value", name="uq_seo_brand_asset_match"),
    )
    op.create_index("ix_seo_brand_assets_tenant_id", "seo_brand_assets", ["tenant_id"])

    op.create_table(
        "seo_serp_results",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("keyword_id", sa.BigInteger(), sa.ForeignKey("seo_keyword_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("engine", sa.String(20), nullable=False, server_default="baidu"),
        sa.Column("device", sa.String(16), nullable=False),
        sa.Column("region", sa.String(80), nullable=False, server_default="全国"),
        sa.Column("rank", sa.SmallInteger(), nullable=False),
        sa.Column("rank_label", sa.String(24)),
        sa.Column("title", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column("result_url", sa.Text(), nullable=False),
        sa.Column("domain", sa.String(255)),
        sa.Column("ownership_type", sa.String(24), nullable=False, server_default="unresolved"),
        sa.Column("match_method", sa.String(24), nullable=False, server_default="none"),
        sa.Column("confidence", sa.SmallInteger()),
        sa.Column("matched_asset_id", sa.BigInteger(), sa.ForeignKey("seo_brand_assets.id", ondelete="SET NULL")),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider", sa.String(24), nullable=False, server_default="chinaz"),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_seo_serp_results_tenant_id", "seo_serp_results", ["tenant_id"])
    op.create_index("ix_seo_serp_results_keyword_id", "seo_serp_results", ["keyword_id"])
    op.create_index(
        "ix_seo_serp_latest",
        "seo_serp_results",
        ["tenant_id", "keyword_id", "device", "captured_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_seo_serp_latest", table_name="seo_serp_results")
    op.drop_index("ix_seo_serp_results_keyword_id", table_name="seo_serp_results")
    op.drop_index("ix_seo_serp_results_tenant_id", table_name="seo_serp_results")
    op.drop_table("seo_serp_results")
    op.drop_index("ix_seo_brand_assets_tenant_id", table_name="seo_brand_assets")
    op.drop_table("seo_brand_assets")
