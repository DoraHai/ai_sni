"""assistant_messages 对话持久化（单条连续流，保留近 90 天）

Revision ID: 0027_assistant_messages
Revises: 0026_assistant
Create Date: 2026-06-28

AI 助手对话落库，进页面加载历史。保留策略 90 天（scheduler 每日清理）。对话文本体量极小。
关键信息走 tenant_memories（不受此保留期影响）。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027_assistant_messages"
down_revision: Union[str, None] = "0026_assistant"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_assistant_messages_tenant_time", "assistant_messages", ["tenant_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_messages_tenant_time", table_name="assistant_messages")
    op.drop_table("assistant_messages")
