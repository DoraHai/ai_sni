"""tenant_memories 客户长期记忆 + 给内置角色补 assistant 菜单权限

Revision ID: 0026_assistant
Revises: 0025_kw_conversions
Create Date: 2026-06-26

AI 对话助手（欢迎页）：开放式记忆条目表（不硬加字段、应对无法穷举的关键信息）。
新菜单 assistant 给已存在的内置角色补 view（欢迎页人人可见，含品牌方客户）。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026_assistant"
down_revision: Union[str, None] = "0025_kw_conversions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenant_memories",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("mem_type", sa.String(20), nullable=False, server_default="other"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="assistant"),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("operator_user_id", sa.BigInteger()),
        sa.Column("operator_name", sa.String(100)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_tenant_memories_tenant", "tenant_memories", ["tenant_id", "active"])

    # 新菜单 assistant：内置角色都补 view（欢迎页，管理员/运营/品牌方客户都给）
    op.execute(
        """
        UPDATE roles
        SET permissions = permissions || '{"assistant": "view"}'::jsonb
        WHERE is_system = true
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = permissions - 'assistant'
        WHERE is_system = true
        """
    )
    op.drop_index("ix_tenant_memories_tenant", table_name="tenant_memories")
    op.drop_table("tenant_memories")
