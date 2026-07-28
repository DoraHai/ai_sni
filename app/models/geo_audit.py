from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GeoAuditRun(Base):
    """一次网站 GEO 诊断及其生成资产。"""

    __tablename__ = "geo_audit_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    score: Mapped[int | None] = mapped_column(Integer)
    page_title: Mapped[str | None] = mapped_column(Text)
    page_description: Mapped[str | None] = mapped_column(Text)
    snapshot: Mapped[dict | None] = mapped_column(JSONB)
    findings: Mapped[list | None] = mapped_column(JSONB)
    advice: Mapped[list | None] = mapped_column(JSONB)
    advice_source: Mapped[str | None] = mapped_column(String(20))
    json_ld: Mapped[dict | None] = mapped_column(JSONB)
    llms_text: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
