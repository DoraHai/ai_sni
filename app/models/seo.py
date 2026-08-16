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


class SeoBrandAsset(Base):
    """用于识别搜索结果归属的官网、品牌内容 URL 与平台账号规则。"""

    __tablename__ = "seo_brand_assets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    asset_type: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    match_value: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "asset_type", "match_value", name="uq_seo_brand_asset_match"
        ),
    )


class SeoSerpResult(Base):
    """站长之家前 50 搜索结果及品牌归属判断。"""

    __tablename__ = "seo_serp_results"

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
    engine: Mapped[str] = mapped_column(String(20), nullable=False, default="baidu")
    device: Mapped[str] = mapped_column(String(16), nullable=False)
    region: Mapped[str] = mapped_column(String(80), nullable=False, default="全国")
    rank: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    rank_label: Mapped[str | None] = mapped_column(String(24))
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    result_url: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255))
    ownership_type: Mapped[str] = mapped_column(
        String(24), nullable=False, default="unresolved"
    )
    match_method: Mapped[str] = mapped_column(String(24), nullable=False, default="none")
    confidence: Mapped[int | None] = mapped_column(SmallInteger)
    matched_asset_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("seo_brand_assets.id", ondelete="SET NULL")
    )
    is_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider: Mapped[str] = mapped_column(String(24), nullable=False, default="chinaz")
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
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


class SeoContentAsset(Base):
    """SEO 内容任务、草稿与发布资产。"""

    __tablename__ = "seo_content_assets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, index=True)
    keyword_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("seo_keyword_assets.id", ondelete="SET NULL"))
    content_type: Mapped[str] = mapped_column(String(32), nullable=False, default="article")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    outline: Mapped[str | None] = mapped_column(Text)
    draft: Mapped[str | None] = mapped_column(Text)
    humanized_content: Mapped[str | None] = mapped_column(Text)
    source_text: Mapped[str | None] = mapped_column(Text)
    rewrite_progress: Mapped[int | None] = mapped_column(SmallInteger)
    originality_score: Mapped[int | None] = mapped_column(SmallInteger)
    target_platforms: Mapped[list | None] = mapped_column(JSONB)
    version_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="planned")
    page_url: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(120))
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class SeoInternalLink(Base):
    """站内页面之间的实际链接边。"""

    __tablename__ = "seo_internal_links"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, index=True)
    source_page_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("seo_site_pages.id", ondelete="CASCADE"), nullable=False)
    target_page_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("seo_site_pages.id", ondelete="CASCADE"), nullable=False)
    anchor_text: Mapped[str | None] = mapped_column(Text)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "source_page_id", "target_page_id", "anchor_text", name="uq_seo_internal_link_edge"),
    )


class SeoBacklink(Base):
    """外部页面指向客户站点的链接资产。"""

    __tablename__ = "seo_backlinks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, index=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    anchor_text: Mapped[str | None] = mapped_column(Text)
    authority_score: Mapped[int | None] = mapped_column(SmallInteger)
    toxic_score: Mapped[int | None] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "source_url", "target_url", name="uq_seo_backlink_source_target"),
    )


class SeoCompetitor(Base):
    """SEO 竞品域名资产。"""

    __tablename__ = "seo_competitors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("tenant_id", "domain", name="uq_seo_competitor_domain"),)


class SeoCompetitorEvent(Base):
    """竞品新内容和新外链等可追踪动态。"""

    __tablename__ = "seo_competitor_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, index=True)
    competitor_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("seo_competitors.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    event_at: Mapped[datetime | None] = mapped_column(DateTime)
    detected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("tenant_id", "competitor_id", "event_type", "url", name="uq_seo_competitor_event"),)
