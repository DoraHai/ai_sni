"""Historical, human reviewed AI suggestions for stored SEO pages."""
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SeoPageAiTdkSuggestion(Base):
    __tablename__ = "seo_page_ai_tdk_suggestions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    site_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("seo_sites.id", ondelete="CASCADE"), nullable=False)
    page_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("seo_site_pages.id", ondelete="CASCADE"), nullable=False)
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    title_ai_value: Mapped[str | None] = mapped_column(Text)
    title_final_value: Mapped[str | None] = mapped_column(Text)
    title_status: Mapped[str] = mapped_column(String(16), nullable=False, default="ai_draft")
    title_reviewed_by: Mapped[int | None] = mapped_column(BigInteger)
    title_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    description_ai_value: Mapped[str | None] = mapped_column(Text)
    description_final_value: Mapped[str | None] = mapped_column(Text)
    description_status: Mapped[str] = mapped_column(String(16), nullable=False, default="ai_draft")
    description_reviewed_by: Mapped[int | None] = mapped_column(BigInteger)
    description_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    keywords_ai_value: Mapped[str | None] = mapped_column(Text)
    keywords_final_value: Mapped[str | None] = mapped_column(Text)
    keywords_status: Mapped[str] = mapped_column(String(16), nullable=False, default="ai_draft")
    keywords_reviewed_by: Mapped[int | None] = mapped_column(BigInteger)
    keywords_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)
    internal_link_suggestions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    warnings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    dropped_links: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_response_excerpt: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_seo_page_ai_tdk_scope_latest", "tenant_id", "site_id", "page_id", "id"),
        *(CheckConstraint(f"{field}_status IN ('ai_draft','confirmed','modified','rejected')", name=f"ck_seo_page_ai_tdk_{field}_status") for field in ("title", "description", "keywords")),
    )
