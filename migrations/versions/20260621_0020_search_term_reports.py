"""search_term_reports（搜索词报告全量落库）+ 新增「搜索词报告」菜单补角色权限

Revision ID: 0020_search_term_reports
Revises: 0019_bid_writebacks
Create Date: 2026-06-21

搜索词报告全量快照（含已添加词），供搜索词报告页 + 关键词详情触发搜索词下钻 + 加否词/转拓词。
新增菜单 optimize.searchterms（搜索词报告，归优化执行）→ 给内置角色补权限（管理员/运营 edit）。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_search_term_reports"
down_revision: Union[str, None] = "0019_bid_writebacks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "search_term_reports",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "baidu_account_id", sa.BigInteger(), sa.ForeignKey("baidu_accounts.id"), nullable=True
        ),
        sa.Column("query_word", sa.Text(), nullable=False),
        sa.Column("trigger_keyword", sa.Text(), nullable=True),
        sa.Column("query_status", sa.SmallInteger(), nullable=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=True),
        sa.Column("campaign_name", sa.Text(), nullable=True),
        sa.Column("adgroup_id", sa.BigInteger(), nullable=True),
        sa.Column("adgroup_name", sa.Text(), nullable=True),
        sa.Column("match_id", sa.SmallInteger(), nullable=True),
        sa.Column("impression", sa.BigInteger(), nullable=True),
        sa.Column("click", sa.BigInteger(), nullable=True),
        sa.Column("cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("ctr", sa.Numeric(8, 4), nullable=True),
        sa.Column("cpc", sa.Numeric(10, 2), nullable=True),
        sa.Column("window_start", sa.Date(), nullable=True),
        sa.Column("window_end", sa.Date(), nullable=True),
        sa.Column("is_added", sa.Boolean(), server_default=sa.false()),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_search_term_reports_tenant_adgroup",
        "search_term_reports",
        ["tenant_id", "adgroup_id"],
    )
    op.create_index(
        "ix_search_term_reports_tenant_word",
        "search_term_reports",
        ["tenant_id", "query_word"],
    )
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE roles SET permissions = permissions || '{\"optimize.searchterms\":\"edit\"}'::jsonb "
        "WHERE name IN ('管理员', '运营')"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE roles SET permissions = permissions - 'optimize.searchterms'"))
    op.drop_index("ix_search_term_reports_tenant_word", table_name="search_term_reports")
    op.drop_index("ix_search_term_reports_tenant_adgroup", table_name="search_term_reports")
    op.drop_table("search_term_reports")
