"""GEO 可见度全自动巡检运行记录。"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GeoVisibilityPatrolRun(Base):
    """一次全自动可见度巡检（多机会词 × 多引擎，可自动落库快照）。"""

    __tablename__ = "geo_visibility_patrol_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending"
    )  # pending|running|completed|failed|cancelled
    trigger: Mapped[str] = mapped_column(
        String(24), nullable=False, default="manual"
    )  # manual|schedule
    auto_persist: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    prefer_real: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    prompt_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    engine_keys: Mapped[list | None] = mapped_column(JSONB)  # null = all enabled
    summary: Mapped[dict | None] = mapped_column(JSONB)
    items: Mapped[list | None] = mapped_column(JSONB)  # per cell results
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class GeoVisibilityPatrolSettings(Base):
    """租户级巡检开关（定时全自动）。"""

    __tablename__ = "geo_visibility_patrol_settings"

    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # cron: hour of day Asia/Shanghai for daily run (0-23)
    daily_hour: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    auto_persist: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    prefer_real: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    prompt_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    engine_keys: Mapped[list | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
