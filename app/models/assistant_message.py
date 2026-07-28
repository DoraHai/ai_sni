from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AssistantMessage(Base):
    """AI 对话助手的聊天记录（持久化，按用户隔离）。

    存全量、喂 AI 只取滑动窗口最近 N 条（存库便宜、喂 LLM 贵，两回事）。保留策略：定时清
    90 天前的（scheduler 每日任务）。聊天历史是用户私有；关键信息（KPI/约束）不靠这里记，
    走 tenant_memories，按客户共享且不随保留期清理。
    """

    __tablename__ = "assistant_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(10), nullable=False)  # user / assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_assistant_messages_tenant_user_time", "tenant_id", "user_id", "created_at"),
    )
