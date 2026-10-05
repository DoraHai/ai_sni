"""Per-site analytics credentials, monthly measurements and export columns."""

from datetime import datetime
from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class SeoSiteAnalyticsSource(Base):
    __tablename__ = "seo_site_analytics_sources"
    __table_args__ = (UniqueConstraint("site_id", "source"), CheckConstraint("source IN ('baidu_tongji','ga4')"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    site_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("seo_sites.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    secret_ciphertext: Mapped[str | None] = mapped_column(Text)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_status: Mapped[str | None] = mapped_column(String(16))
    last_test_message: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    updated_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SeoSiteAnalyticsMonthly(Base):
    __tablename__ = "seo_site_analytics_monthly"
    __table_args__ = (UniqueConstraint("site_id", "source", "month"), CheckConstraint("status IN ('ok','no_data','failed')"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    site_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("seo_sites.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    month: Mapped[str] = mapped_column(String(7), nullable=False)
    uv: Mapped[int | None] = mapped_column(BigInteger)
    pv: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(48))
    error_message: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_by: Mapped[int | None] = mapped_column(BigInteger)
    raw_meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_error_code: Mapped[str | None] = mapped_column(String(48))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SeoSiteExportTemplate(Base):
    __tablename__ = "seo_site_export_templates"
    site_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("seo_sites.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    columns: Mapped[list] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
