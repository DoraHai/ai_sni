from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# 开放式记忆条目类型（不预定义字段、用类型标签分类，应对无法穷举的关键信息）
MEMORY_TYPE_LABELS = {
    "goal": "目标",          # 目标线索成本、月预算等 KPI
    "constraint": "约束",    # 不投品牌词、红线
    "preference": "偏好",    # 主推产品线、侧重
    "background": "背景",    # 旺季、行业背景
    "decision": "决策",      # 停某条线等阶段性决定
    "other": "其他",
}


class TenantMemory(Base):
    """客户长期记忆（AI 对话助手的开放式记忆条目）。

    不靠对话历史记忆关键信息（会随窗口滑走），也不硬加字段（无法穷举）：每条是一段
    自由文本的关键信息（目标/约束/偏好/背景/决策），AI 从对话抽取→人确认→落库，
    每轮对话全量喂回 prompt。量大了再上语义检索。少数要参与计算的 KPI 另结构化。
    """

    __tablename__ = "tenant_memories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)

    mem_type: Mapped[str] = mapped_column(String(20), nullable=False, default="other")
    content: Mapped[str] = mapped_column(Text, nullable=False)  # 自由文本的关键信息

    source: Mapped[str] = mapped_column(String(20), nullable=False, default="assistant")  # assistant/manual
    confirmed: Mapped[bool] = mapped_column(default=True, nullable=False)  # AI 抽取需人确认；手动录入默认 True
    active: Mapped[bool] = mapped_column(default=True, nullable=False)  # 软删除：失效的不喂 prompt

    operator_user_id: Mapped[int | None] = mapped_column(BigInteger)
    operator_name: Mapped[str | None] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())
