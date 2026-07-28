from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DailyInsight(Base):
    """AI 每日洞察（盯盘页）。

    基于当天 KPI + 环比 + 设备分布 + open 告警 + 趋势，DeepSeek 生成「今日要点」。
    按 (tenant_id, insight_date) 缓存——每天生成一次（AI 调用有成本、且当天结论应稳定）。
    未配 DEEPSEEK_API_KEY 时不生成（盯盘页不显示洞察卡）。
    """

    __tablename__ = "daily_insights"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    insight_date: Mapped[date] = mapped_column(Date, nullable=False)

    summary: Mapped[str] = mapped_column(Text, nullable=False)  # 今日要点摘要
    # 结构化明细（highlights / actions 数组）+ 生成时的数据快照
    detail: Mapped[dict | None] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(Text)  # 生成模型，如 deepseek-chat

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "insight_date", name="uq_daily_insight_tenant_date"),
    )
