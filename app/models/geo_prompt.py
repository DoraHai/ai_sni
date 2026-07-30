from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GeoPrompt(Base):
    """GEO 机会问题（目标提问）。"""

    __tablename__ = "geo_prompts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="zh-CN")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tags: Mapped[list | None] = mapped_column(JSONB)
    demand_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
