"""assistant_messages 按登录用户隔离

Revision ID: 0032_assistant_user_scope
Revises: 0031_adgroup_manage_menu
Create Date: 2026-07-02

聊天记录是用户私有；客户记忆 tenant_memories 仍按 tenant 共享。
历史旧消息没有 user_id，迁移后保留但不展示给普通登录用户。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032_assistant_user_scope"
down_revision: Union[str, None] = "0031_adgroup_manage_menu"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "assistant_messages",
        sa.Column("user_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_assistant_messages_user_id",
        "assistant_messages",
        "users",
        ["user_id"],
        ["id"],
    )
    op.drop_index("ix_assistant_messages_tenant_time", table_name="assistant_messages")
    op.create_index(
        "ix_assistant_messages_tenant_user_time",
        "assistant_messages",
        ["tenant_id", "user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_messages_tenant_user_time", table_name="assistant_messages")
    op.create_index(
        "ix_assistant_messages_tenant_time",
        "assistant_messages",
        ["tenant_id", "created_at"],
    )
    op.drop_constraint(
        "fk_assistant_messages_user_id",
        "assistant_messages",
        type_="foreignkey",
    )
    op.drop_column("assistant_messages", "user_id")
