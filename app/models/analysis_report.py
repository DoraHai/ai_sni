from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AnalysisReport(Base):
    """自定义日期区间分析报告的 AI 叙述缓存。"""

    __tablename__ = "analysis_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    summary: Mapped[str | None] = mapped_column(Text)
    # {"module_comments": {模块key: 点评}, "next_period_plan": [..]}
    narrative: Mapped[dict | None] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(Text)

    generated_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "start_date",
            "end_date",
            name="uq_analysis_report_tenant_period",
        ),
    )
