"""kw_report_snapshots 加 conversions 列（ocpcConversionsDetail2 电话按钮点击量）

Revision ID: 0025_kw_conversions
Revises: 0024_leads_baidu_sync
Create Date: 2026-06-26

转化层接入：关键词报告补 Detail2 转化列并落库，供工作台/详情展示词级转化数+转化成本、
后续喂 AI 砍"烧钱零转化"的词。历史快照无此列 → 默认 0；重新同步当日报告即回填。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025_kw_conversions"
down_revision: Union[str, None] = "0024_leads_baidu_sync"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "kw_report_snapshots",
        sa.Column("conversions", sa.BigInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("kw_report_snapshots", "conversions")
