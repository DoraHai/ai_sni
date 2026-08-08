from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GeoTrackingEngine(Base):
    """租户监测的 AI 引擎清单（Wave B2；不做自动抓取）。"""

    __tablename__ = "geo_tracking_engines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "engine_key", name="uq_geo_tracking_engines_tenant_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    engine_key: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    note: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # P2: mock_persona (default) | openai_compat (real OpenAI-compatible endpoint)
    sample_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="mock_persona")
    api_base_url: Mapped[str | None] = mapped_column(String(300))
    model: Mapped[str | None] = mapped_column(String(80))
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
