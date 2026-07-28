"""add keyword_candidates (拓词候选词，4 源聚合只读)

Revision ID: 0009_keyword_candidates
Revises: 0008_operation_records
Create Date: 2026-06-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0009_keyword_candidates"
down_revision: Union[str, None] = "0008_operation_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "keyword_candidates",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "baidu_account_id", sa.BigInteger(), sa.ForeignKey("baidu_accounts.id"), nullable=True
        ),
        sa.Column("word", sa.Text(), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("seed_word", sa.Text(), nullable=True),
        sa.Column("monthly_pv", sa.BigInteger(), nullable=True),
        sa.Column("pc_pv", sa.BigInteger(), nullable=True),
        sa.Column("mobile_pv", sa.BigInteger(), nullable=True),
        sa.Column("competition", sa.SmallInteger(), nullable=True),
        sa.Column("recommend_price_pc", sa.Numeric(8, 2), nullable=True),
        sa.Column("recommend_price_mobile", sa.Numeric(8, 2), nullable=True),
        sa.Column("show_reasons", JSONB(), nullable=True),
        sa.Column("impression", sa.BigInteger(), nullable=True),
        sa.Column("click", sa.BigInteger(), nullable=True),
        sa.Column("cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("matched_keyword", sa.Text(), nullable=True),
        sa.Column("potential_score", sa.Numeric(3, 1), nullable=True),
        sa.Column("suggested_category", sa.String(10), nullable=True),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("status_updated_at", sa.DateTime(), nullable=True),
        sa.Column("raw", JSONB(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id", "word", "source", name="uq_kw_candidates_tenant_word_src"
        ),
    )
    op.create_index(
        "ix_kw_candidates_tenant_score",
        "keyword_candidates",
        ["tenant_id", "potential_score"],
    )


def downgrade() -> None:
    op.drop_index("ix_kw_candidates_tenant_score", table_name="keyword_candidates")
    op.drop_table("keyword_candidates")
