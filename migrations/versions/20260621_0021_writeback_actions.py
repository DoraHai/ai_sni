"""writeback_actions（加否词 / 转拓词 写回台账）

Revision ID: 0021_writeback_actions
Revises: 0020_search_term_reports
Create Date: 2026-06-21

非出价类写回台账：加否词（updateAdgroup 追加否词）、转拓词（addWord 加关键词）。
同走 dry-run 安全网。复用 optimize.searchterms 菜单（搜索词页触发），不新增菜单。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021_writeback_actions"
down_revision: Union[str, None] = "0020_search_term_reports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "writeback_actions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "baidu_account_id", sa.BigInteger(), sa.ForeignKey("baidu_accounts.id"), nullable=True
        ),
        sa.Column("action_type", sa.String(20), nullable=False),
        sa.Column("word", sa.Text(), nullable=False),
        sa.Column("match_mode", sa.String(10), nullable=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=True),
        sa.Column("campaign_name", sa.Text(), nullable=True),
        sa.Column("adgroup_id", sa.BigInteger(), nullable=True),
        sa.Column("adgroup_name", sa.Text(), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("baidu_response", sa.Text(), nullable=True),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("operator_user_id", sa.BigInteger(), nullable=True),
        sa.Column("operator_name", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_writeback_actions_tenant_created",
        "writeback_actions",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_writeback_actions_tenant_created", table_name="writeback_actions")
    op.drop_table("writeback_actions")
