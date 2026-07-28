"""adjustment_reviews（调价后验证 R-10）+ 角色补 verify.pending 菜单权限

Revision ID: 0018_adjustment_reviews
Revises: 0017_customer_profile
Create Date: 2026-06-16

待验证调价：按 operation_records.dedup_key 存人工验证状态 + 判定 + AI 研判缓存。
新增 verify.pending 菜单 → 给内置角色补权限（管理员/运营 edit、品牌方客户 view）。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018_adjustment_reviews"
down_revision: Union[str, None] = "0017_customer_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "adjustment_reviews",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("dedup_key", sa.String(32), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("verdict", sa.String(10), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("ai_verdict", sa.String(10), nullable=True),
        sa.Column("ai_reason", sa.Text(), nullable=True),
        sa.Column("ai_generated_at", sa.DateTime(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "dedup_key", name="uq_adj_review_tenant_dedup"),
    )
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE roles SET permissions = permissions || '{\"verify.pending\":\"edit\"}'::jsonb "
        "WHERE name IN ('管理员', '运营')"
    ))
    conn.execute(sa.text(
        "UPDATE roles SET permissions = permissions || '{\"verify.pending\":\"view\"}'::jsonb "
        "WHERE name = '品牌方客户'"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE roles SET permissions = permissions - 'verify.pending'"))
    op.drop_table("adjustment_reviews")
