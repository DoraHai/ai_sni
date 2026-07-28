from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MonthlyReport(Base):
    """AI 月度分析报告的叙述缓存（客户交付页）。

    报告的数据模块每次实时聚合（KPI/环比/趋势/分类/TOP词/设备/告警/操作——数字不依赖 AI）；
    本表只缓存 AI 叙述（总览摘要 / 各模块点评 / 下月计划），按 (tenant_id, year, month) 唯一。
    AI 调用有成本且过往月份结论应稳定 → 缓存；force 重算。未配 DeepSeek 时报告照出数据、
    叙述为空。
    """

    __tablename__ = "monthly_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    month: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    summary: Mapped[str | None] = mapped_column(Text)  # 总览摘要
    # {"module_comments": {模块key: 点评}, "next_month_plan": [..]}
    narrative: Mapped[dict | None] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(Text)

    generated_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "year", "month", name="uq_monthly_report_tenant_ym"),
    )
