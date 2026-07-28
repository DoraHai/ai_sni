"""keyword_candidates 加 AI 建议出价 + 理由

Revision ID: 0022_candidate_ai_bid
Revises: 0021_writeback_actions
Create Date: 2026-06-23

拓词「加入计划」的默认出价 + 小字依据：AI 评估时顺带给建议首次出价 + 理由（新词无效果数据，
依据百度指导价/竞争度/搜索量）。两列默认 NULL，未配 DeepSeek 或未重跑评估时不影响其余功能。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022_candidate_ai_bid"
down_revision: Union[str, None] = "0021_writeback_actions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("keyword_candidates", sa.Column("ai_suggested_bid", sa.Numeric(8, 2), nullable=True))
    op.add_column("keyword_candidates", sa.Column("ai_bid_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("keyword_candidates", "ai_bid_reason")
    op.drop_column("keyword_candidates", "ai_suggested_bid")
