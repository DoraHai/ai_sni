"""GEO 优化期次：交付/对比/归因的时间边界实体。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GeoOptimizationPeriod(Base):
    """一个优化期次 = 时间窗 + 目标业务 + 期初基线 + 期内发布清单 + 期末结果。"""

    __tablename__ = "geo_optimization_periods"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    business_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("geo_optimization_businesses.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # planned | active | closed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    goal_note: Mapped[str | None] = mapped_column(Text)
    baseline_meta: Mapped[dict | None] = mapped_column(JSONB)
    result_meta: Mapped[dict | None] = mapped_column(JSONB)
    publication_ids: Mapped[list | None] = mapped_column(JSONB)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
