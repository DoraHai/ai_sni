"""add monthly_reports (AI 月度分析报告叙述缓存)

Revision ID: 0015_monthly_reports
Revises: 0014_candidate_ai_eval
Create Date: 2026-06-15

月报数据模块每次实时聚合（数字不依赖 AI）；本表只缓存 AI 叙述（摘要/各模块点评/下月计划），
按 (tenant_id, year, month) 唯一。未配 DeepSeek 时报告照常出数据、无 AI 文字。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_monthly_reports"
down_revision: Union[str, None] = "0014_candidate_ai_eval"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monthly_reports",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("month", sa.SmallInteger(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("narrative", postgresql.JSONB(), nullable=True),  # module_comments + next_month_plan
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "year", "month", name="uq_monthly_report_tenant_ym"),
    )


def downgrade() -> None:
    op.drop_table("monthly_reports")
