"""Append-only metadata for SEO page evidence."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base


class SeoPageCapture(Base):
    __tablename__ = "seo_page_captures"
    __table_args__ = (
        Index("ix_seo_page_captures_scope", "tenant_id", "site_id", "relation_type", "relation_id"),
        CheckConstraint("status IN ('succeeded', 'failed')", name="ck_seo_page_captures_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("seo_sites.id"), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(24), nullable=False)
    relation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    redirect_chain: Mapped[list] = mapped_column(JSONB, nullable=False)
    warnings: Mapped[dict] = mapped_column(JSONB, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(40))
    viewport_width: Mapped[int] = mapped_column(Integer, nullable=False)
    viewport_height: Mapped[int] = mapped_column(Integer, nullable=False)
    image_width: Mapped[int | None] = mapped_column(Integer)
    image_height: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    storage_key: Mapped[str | None] = mapped_column(String(120))
