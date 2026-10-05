"""Site scoped TDK review export audit and layout settings."""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SeoTdkReviewBatch(Base):
    __tablename__ = "seo_tdk_review_batches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    site_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("seo_sites.id", ondelete="CASCADE"), nullable=False)
    page_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class SeoSiteTdkReviewTemplate(Base):
    __tablename__ = "seo_site_tdk_review_templates"

    site_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("seo_sites.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    sections: Mapped[list] = mapped_column(JSONB, nullable=False)
    columns: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
