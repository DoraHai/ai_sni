"""add candidate AI evaluation columns (拓词候选语义相关性研判)

Revision ID: 0014_candidate_ai_eval
Revises: 0013_daily_insights
Create Date: 2026-06-15

只加相关性研判维度（用户 2026-06-15 拍板），不动现有 potential_score / suggested_category。
ai_relevance: relevant / generic / irrelevant；ai_recommend: adopt / watch / drop。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_candidate_ai_eval"
down_revision: Union[str, None] = "0013_daily_insights"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("keyword_candidates", sa.Column("ai_relevance", sa.String(12), nullable=True))
    op.add_column("keyword_candidates", sa.Column("ai_recommend", sa.String(12), nullable=True))
    op.add_column("keyword_candidates", sa.Column("ai_reason", sa.Text(), nullable=True))
    op.add_column("keyword_candidates", sa.Column("ai_evaluated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("keyword_candidates", "ai_evaluated_at")
    op.drop_column("keyword_candidates", "ai_reason")
    op.drop_column("keyword_candidates", "ai_recommend")
    op.drop_column("keyword_candidates", "ai_relevance")
