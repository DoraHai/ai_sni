from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SeoKeywordAsset(Base):
    """SEO 自然搜索关键词资产，与 SEM 已购关键词严格分表。"""

    __tablename__ = "seo_keyword_assets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    keyword: Mapped[str] = mapped_column(Text, nullable=False)
    cluster: Mapped[str | None] = mapped_column(String(120))
    intent: Mapped[str | None] = mapped_column(String(24))
    monthly_volume: Mapped[int | None] = mapped_column(BigInteger)
    difficulty: Mapped[int | None] = mapped_column(SmallInteger)
    priority: Mapped[str] = mapped_column(String(4), nullable=False, default="P2")
    landing_page: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "keyword", name="uq_seo_keyword_tenant_word"),
    )


class SeoRankSnapshot(Base):
    """一次自然排名观测；支持自有域名与竞品域名使用同一数据口径。"""

    __tablename__ = "seo_rank_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    keyword_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("seo_keyword_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    engine: Mapped[str] = mapped_column(String(20), nullable=False)
    device: Mapped[str] = mapped_column(String(16), nullable=False, default="desktop")
    region: Mapped[str] = mapped_column(String(80), nullable=False, default="全国")
    domain: Mapped[str | None] = mapped_column(String(255))
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False, default="own")
    rank: Mapped[int | None] = mapped_column(SmallInteger)
    result_url: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SeoSitePage(Base):
    """站内页面资产及最近一次技术/TDK 检测结果。"""

    __tablename__ = "seo_site_pages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    page_type: Mapped[str | None] = mapped_column(String(32))
    target_keyword_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("seo_keyword_assets.id", ondelete="SET NULL")
    )
    title: Mapped[str | None] = mapped_column(Text)
    meta_description: Mapped[str | None] = mapped_column(Text)
    meta_keywords: Mapped[str | None] = mapped_column(Text)
    h1: Mapped[str | None] = mapped_column(Text)
    canonical: Mapped[str | None] = mapped_column(Text)
    indexable: Mapped[bool | None] = mapped_column(Boolean)
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_units: Mapped[int | None] = mapped_column(Integer)
    audit_score: Mapped[int | None] = mapped_column(SmallInteger)
    issue_codes: Mapped[list | None] = mapped_column(JSONB)
    title_suggestion: Mapped[str | None] = mapped_column(Text)
    description_suggestion: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    last_error: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "url", name="uq_seo_site_page_tenant_url"),
    )
