"""keyword region/hourly performance reports

Revision ID: 0034_keyword_dimension_reports
Revises: 0033_adgroup_landing_urls
Create Date: 2026-07-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0034_keyword_dimension_reports"
down_revision: Union[str, None] = "0033_adgroup_landing_urls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "keyword_region_reports",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("baidu_account_id", sa.BigInteger(), sa.ForeignKey("baidu_accounts.id"), nullable=True),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=True),
        sa.Column("campaign_name", sa.Text(), nullable=True),
        sa.Column("adgroup_id", sa.BigInteger(), nullable=True),
        sa.Column("adgroup_name", sa.Text(), nullable=True),
        sa.Column("keyword_id", sa.BigInteger(), nullable=False),
        sa.Column("keyword", sa.Text(), nullable=True),
        sa.Column("device", sa.SmallInteger(), nullable=True),
        sa.Column("region_name", sa.Text(), nullable=False),
        sa.Column("region_level", sa.Text(), nullable=False, server_default="city"),
        sa.Column("impression", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("click", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cost", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("cpc", sa.Numeric(10, 2), nullable=True),
        sa.Column("ctr", sa.Numeric(8, 6), nullable=True),
        sa.Column("raw_metrics", postgresql.JSONB(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id",
            "report_date",
            "keyword_id",
            "region_name",
            "region_level",
            "device",
            name="uq_kw_region_report_tenant_date_kw_region_device",
        ),
    )
    op.create_index(
        "ix_keyword_region_reports_kw_period",
        "keyword_region_reports",
        ["tenant_id", "keyword_id", "report_date"],
    )

    op.create_table(
        "keyword_hourly_reports",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("baidu_account_id", sa.BigInteger(), sa.ForeignKey("baidu_accounts.id"), nullable=True),
        sa.Column("report_datetime", sa.DateTime(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("hour", sa.SmallInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=True),
        sa.Column("campaign_name", sa.Text(), nullable=True),
        sa.Column("adgroup_id", sa.BigInteger(), nullable=True),
        sa.Column("adgroup_name", sa.Text(), nullable=True),
        sa.Column("keyword_id", sa.BigInteger(), nullable=False),
        sa.Column("keyword", sa.Text(), nullable=True),
        sa.Column("device", sa.SmallInteger(), nullable=True),
        sa.Column("impression", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("click", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cost", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("cpc", sa.Numeric(10, 2), nullable=True),
        sa.Column("ctr", sa.Numeric(8, 6), nullable=True),
        sa.Column("raw_metrics", postgresql.JSONB(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id",
            "report_datetime",
            "keyword_id",
            "device",
            name="uq_kw_hourly_report_tenant_dt_kw_device",
        ),
    )
    op.create_index(
        "ix_keyword_hourly_reports_kw_period",
        "keyword_hourly_reports",
        ["tenant_id", "keyword_id", "report_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_keyword_hourly_reports_kw_period", table_name="keyword_hourly_reports")
    op.drop_table("keyword_hourly_reports")
    op.drop_index("ix_keyword_region_reports_kw_period", table_name="keyword_region_reports")
    op.drop_table("keyword_region_reports")
