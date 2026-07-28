"""add kw_report_snapshots

Revision ID: 0002_kw_report_snapshots
Revises: 0001_initial
Create Date: 2026-06-10

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_kw_report_snapshots"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kw_report_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "baidu_account_id",
            sa.BigInteger(),
            sa.ForeignKey("baidu_accounts.id"),
            nullable=True,
        ),
        # 维度
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=True),
        sa.Column("campaign_name", sa.Text(), nullable=True),
        sa.Column("adgroup_id", sa.BigInteger(), nullable=True),
        sa.Column("adgroup_name", sa.Text(), nullable=True),
        sa.Column("keyword_id", sa.BigInteger(), nullable=True),
        sa.Column("keyword", sa.Text(), nullable=True),
        sa.Column("match_type", sa.SmallInteger(), nullable=True),
        sa.Column("device", sa.SmallInteger(), nullable=True),
        # 效果指标
        sa.Column("impression", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("click", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cost", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("cpc", sa.Numeric(8, 2), nullable=True),
        sa.Column("ctr", sa.Numeric(8, 6), nullable=True),
        sa.Column("avg_rank", sa.Numeric(6, 2), nullable=True),
        # 质量度 & 评分
        sa.Column("quality_enum", sa.SmallInteger(), nullable=True),
        sa.Column("estimated_click_rate", sa.SmallInteger(), nullable=True),
        sa.Column("business_relationship", sa.SmallInteger(), nullable=True),
        sa.Column("land_page_experience", sa.SmallInteger(), nullable=True),
        # 上方位指标
        sa.Column("top_pageviews", sa.BigInteger(), nullable=True),
        sa.Column("top_pclicks", sa.BigInteger(), nullable=True),
        sa.Column("top_pay", sa.Numeric(12, 2), nullable=True),
        sa.Column("top_pv_win_a", sa.Numeric(8, 6), nullable=True),
        sa.Column("top_first_pv_win_a", sa.Numeric(8, 6), nullable=True),
        # 出价
        sa.Column("bid_new", sa.Numeric(8, 2), nullable=True),
        # 原始指标
        sa.Column("raw_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "report_date",
            "keyword_id",
            "device",
            name="uq_kw_report_tenant_date_kw_device",
        ),
    )
    op.create_index(
        "ix_kw_report_snapshots_tenant_date",
        "kw_report_snapshots",
        ["tenant_id", sa.text("report_date DESC")],
    )
    op.create_index(
        "ix_kw_report_snapshots_keyword",
        "kw_report_snapshots",
        ["keyword_id", sa.text("report_date DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_kw_report_snapshots_keyword", table_name="kw_report_snapshots")
    op.drop_index("ix_kw_report_snapshots_tenant_date", table_name="kw_report_snapshots")
    op.drop_table("kw_report_snapshots")
