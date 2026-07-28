"""bid_writebacks（调价回写台账）

Revision ID: 0019_bid_writebacks
Revises: 0018_adjustment_reviews
Create Date: 2026-06-21

平台主动发起的出价写回（updateWord）逐条留痕：旧价快照/目标价/是否演练(dry_run)/
百度返回/操作人，用于审计 + 回滚依据。复用现有菜单（回写=optimize.keywords edit、
台账查看=verify.adjustments view），不新增菜单 → 无需补 RBAC 权限。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_bid_writebacks"
down_revision: Union[str, None] = "0018_adjustment_reviews"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bid_writebacks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "baidu_account_id", sa.BigInteger(), sa.ForeignKey("baidu_accounts.id"), nullable=True
        ),
        sa.Column("suggestion_id", sa.BigInteger(), nullable=True),
        sa.Column("keyword_id", sa.BigInteger(), nullable=False),
        sa.Column("keyword", sa.Text(), nullable=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=True),
        sa.Column("campaign_name", sa.Text(), nullable=True),
        sa.Column("adgroup_id", sa.BigInteger(), nullable=True),
        sa.Column("old_bid", sa.Numeric(10, 2), nullable=True),
        sa.Column("new_bid", sa.Numeric(10, 2), nullable=False),
        sa.Column("change_pct", sa.Numeric(6, 2), nullable=True),
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
        "ix_bid_writebacks_tenant_created",
        "bid_writebacks",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_bid_writebacks_tenant_created", table_name="bid_writebacks")
    op.drop_table("bid_writebacks")
