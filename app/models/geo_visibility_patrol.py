"""GEO 可见度全自动巡检运行记录。"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GeoVisibilityPatrolRun(Base):
    """一次全自动可见度巡检（多机会词 × 多引擎，可自动落库快照）。"""

    __tablename__ = "geo_visibility_patrol_runs"
    __table_args__ = (Index("uq_geo_patrol_tenant_auto_day", "tenant_id", "auto_day",
                           unique=True, postgresql_where=text("auto_day IS NOT NULL")),)

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
    auto_day: Mapped[date | None] = mapped_column(Date)
    last_progress_at: Mapped[datetime | None] = mapped_column(DateTime)
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
    # legacy single-hour trigger (kept for compat; synced to window_start_hour on write)
    daily_hour: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    # allowed execution window in Asia/Shanghai local hours (inclusive)
    window_start_hour: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    window_end_hour: Mapped[int] = mapped_column(Integer, nullable=False, default=22)
    # minimum hours between scheduled runs (1–24)
    interval_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    last_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime)
    auto_persist: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    prefer_real: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    prompt_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    engine_keys: Mapped[list | None] = mapped_column(JSONB)
    schedule_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="legacy", server_default="legacy")
    self_service_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    owner_user_id: Mapped[int | None] = mapped_column(BigInteger)
    owner_grant_id: Mapped[int | None] = mapped_column(BigInteger)
    owner_scope: Mapped[dict | None] = mapped_column(JSONB)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    admin_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    lock_reason: Mapped[str | None] = mapped_column(String(500))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime)
    opened_by: Mapped[int | None] = mapped_column(BigInteger)
    last_changed_by: Mapped[int | None] = mapped_column(BigInteger)
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime)
    blocked_reason: Mapped[str | None] = mapped_column(String(64))
    manual_daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=10, server_default="10")
    manual_limit_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class GeoVisibilityPatrolSettingEvent(Base):
    """Append-only switch and manual limit audit, classified by action."""
    __tablename__ = "geo_visibility_patrol_setting_events"
    __table_args__ = (Index("ix_geo_patrol_events_tenant_id", "tenant_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(BigInteger)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    before: Mapped[dict] = mapped_column(JSONB, nullable=False)
    after: Mapped[dict] = mapped_column(JSONB, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class GeoVisibilityPatrolDailyBudget(Base):
    """Committed model attempts by Beijing request day, across all workers."""
    __tablename__ = "geo_visibility_patrol_daily_budget"

    budget_day: Mapped[date] = mapped_column(Date, primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
