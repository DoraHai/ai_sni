from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
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
    site_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("seo_sites.id", ondelete="SET NULL"), index=True
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
        UniqueConstraint("tenant_id", "site_id", "keyword", name="uq_seo_keyword_site_word"),
    )


class SeoRankSnapshot(Base):
    """一次自然排名观测；支持自有域名与竞品域名使用同一数据口径。"""

    __tablename__ = "seo_rank_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    site_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("seo_sites.id", ondelete="SET NULL"), index=True
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
    site_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("seo_sites.id", ondelete="SET NULL"), index=True
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
            "tenant_id", "site_id", "asset_type", "match_value", name="uq_seo_brand_asset_site_match"
        ),
    )


class SeoSerpResult(Base):
    """站长之家前 50 搜索结果及品牌归属判断。"""

    __tablename__ = "seo_serp_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    site_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("seo_sites.id", ondelete="SET NULL"), index=True
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
    site_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("seo_sites.id", ondelete="SET NULL"), index=True
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
        UniqueConstraint("tenant_id", "site_id", "url", name="uq_seo_site_page_site_url"),
    )


class SeoContentAsset(Base):
    """SEO 内容任务、草稿与发布资产。"""

    __tablename__ = "seo_content_assets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, index=True)
    site_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("seo_sites.id", ondelete="SET NULL"), index=True)
    source_page_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("seo_site_pages.id", ondelete="SET NULL"),
        index=True,
    )
    keyword_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("seo_keyword_assets.id", ondelete="SET NULL"))
    keyword_ids: Mapped[list | None] = mapped_column(JSONB)
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

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "site_id",
            "source_page_id",
            name="uq_seo_content_asset_source_page",
        ),
    )


class SeoDistributionConnection(Base):
    """Tenant-owned publishing account or assisted distribution destination."""

    __tablename__ = "seo_distribution_connections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    platform_code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    mode: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")
    base_url: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict | None] = mapped_column(JSONB)
    capabilities: Mapped[list | None] = mapped_column(JSONB)
    credentials_encrypted: Mapped[str | None] = mapped_column(Text)
    has_credentials: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="unconfigured")
    last_error: Mapped[str | None] = mapped_column(Text)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "name", name="uq_seo_distribution_connection_tenant_name"
        ),
    )


class SeoDistributionVariant(Base):
    """Versioned platform-specific copy prepared before a publication task."""

    __tablename__ = "seo_distribution_variants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    content_asset_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("seo_content_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connection_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("seo_distribution_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform_code: Mapped[str] = mapped_column(String(40), nullable=False)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    keyword_checks: Mapped[list | None] = mapped_column(JSONB)
    warnings: Mapped[list | None] = mapped_column(JSONB)
    ai_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    generation_instruction: Mapped[str | None] = mapped_column(Text)
    feedback: Mapped[str | None] = mapped_column(Text)
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "content_asset_id",
            "connection_id",
            "revision_number",
            name="uq_seo_distribution_variant_revision",
        ),
    )


class SeoContentPublication(Base):
    """One content asset published, drafted, or handed off to one destination."""

    __tablename__ = "seo_content_publications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    content_asset_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("seo_content_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connection_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("seo_distribution_connections.id", ondelete="SET NULL"),
        index=True,
    )
    variant_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("seo_distribution_variants.id", ondelete="SET NULL"),
        index=True,
    )
    platform_code: Mapped[str] = mapped_column(String(40), nullable=False)
    platform_name: Mapped[str] = mapped_column(String(120), nullable=False)
    publish_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    source_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    adapted_title: Mapped[str | None] = mapped_column(Text)
    adapted_excerpt: Mapped[str | None] = mapped_column(Text)
    adapted_content: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(String(255))
    page_url: Mapped[str | None] = mapped_column(Text)
    handoff_url: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "content_asset_id",
            "page_url",
            name="uq_seo_publication_asset_url",
        ),
    )


class SeoPublishAttempt(Base):
    """Sanitized audit trail for a publication operation."""

    __tablename__ = "seo_publish_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    publication_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("seo_content_publications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    request_summary: Mapped[dict | None] = mapped_column(JSONB)
    response_summary: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class SeoInternalLink(Base):
    """站内页面之间的实际链接边。"""

    __tablename__ = "seo_internal_links"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, index=True)
    site_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("seo_sites.id", ondelete="SET NULL"), index=True)
    source_page_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("seo_site_pages.id", ondelete="CASCADE"), nullable=False)
    target_page_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("seo_site_pages.id", ondelete="CASCADE"), nullable=False)
    anchor_text: Mapped[str | None] = mapped_column(Text)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "site_id", "source_page_id", "target_page_id", "anchor_text", name="uq_seo_internal_link_site_edge"),
    )


class SeoBacklink(Base):
    """外部页面指向客户站点的链接资产。"""

    __tablename__ = "seo_backlinks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, index=True)
    site_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("seo_sites.id", ondelete="SET NULL"), index=True)
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
        UniqueConstraint("tenant_id", "site_id", "source_url", "target_url", name="uq_seo_backlink_site_source_target"),
    )


class SeoCompetitor(Base):
    """SEO 竞品域名资产。"""

    __tablename__ = "seo_competitors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, index=True)
    site_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("seo_sites.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("tenant_id", "site_id", "domain", name="uq_seo_competitor_site_domain"),)


class SeoCompetitorEvent(Base):
    """竞品新内容和新外链等可追踪动态。"""

    __tablename__ = "seo_competitor_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, index=True)
    site_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("seo_sites.id", ondelete="SET NULL"), index=True)
    competitor_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("seo_competitors.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    event_at: Mapped[datetime | None] = mapped_column(DateTime)
    detected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("tenant_id", "site_id", "competitor_id", "event_type", "url", name="uq_seo_competitor_site_event"),)


class SeoCrawlRun(Base):
    """One bounded crawl execution for an SEO site."""

    __tablename__ = "seo_crawl_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    site_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("seo_sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running", index=True)
    seed_url: Mapped[str] = mapped_column(Text, nullable=False)
    max_urls: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    discovered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fetched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    issue_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class SeoPageSnapshot(Base):
    """Evidence captured for one URL in an SEO crawl run."""

    __tablename__ = "seo_page_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    site_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("seo_sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    crawl_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("seo_crawl_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str | None] = mapped_column(Text)
    discovery_source: Mapped[str] = mapped_column(String(32), nullable=False, default="internal_link")
    click_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status_code: Mapped[int | None] = mapped_column(Integer)
    redirect_chain: Mapped[list | None] = mapped_column(JSONB)
    fetch_error: Mapped[str | None] = mapped_column(Text)
    error_type: Mapped[str | None] = mapped_column(String(40))
    content_type: Mapped[str | None] = mapped_column(String(160))
    content_length: Mapped[int | None] = mapped_column(Integer)
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    raw_html_hash: Mapped[str | None] = mapped_column(String(64))
    robots_allowed: Mapped[bool | None] = mapped_column(Boolean)
    meta_robots: Mapped[str | None] = mapped_column(Text)
    x_robots_tag: Mapped[str | None] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    indexable: Mapped[bool | None] = mapped_column(Boolean)
    title: Mapped[str | None] = mapped_column(Text)
    title_length: Mapped[int | None] = mapped_column(Integer)
    meta_description: Mapped[str | None] = mapped_column(Text)
    description_length: Mapped[int | None] = mapped_column(Integer)
    h1_texts: Mapped[list | None] = mapped_column(JSONB)
    h1_count: Mapped[int | None] = mapped_column(Integer)
    html_lang: Mapped[str | None] = mapped_column(String(40))
    main_content_extractable: Mapped[bool | None] = mapped_column(Boolean)
    main_content_hash: Mapped[str | None] = mapped_column(String(64))
    word_count: Mapped[int | None] = mapped_column(Integer)
    schema_types: Mapped[list | None] = mapped_column(JSONB)
    schema_jsonld_count: Mapped[int | None] = mapped_column(Integer)
    schema_parse_error: Mapped[bool | None] = mapped_column(Boolean)
    internal_links_count: Mapped[int | None] = mapped_column(Integer)
    external_links_count: Mapped[int | None] = mapped_column(Integer)
    images_count: Mapped[int | None] = mapped_column(Integer)
    images_missing_alt_count: Mapped[int | None] = mapped_column(Integer)
    hreflang_tags: Mapped[list | None] = mapped_column(JSONB)
    issue_codes: Mapped[list | None] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("crawl_run_id", "url", name="uq_seo_page_snapshot_run_url"),
    )


class SeoMetricSnapshot(Base):
    """A site-scoped SEO metric observation with explicit provenance and availability."""

    __tablename__ = "seo_metric_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    site_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("seo_sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    dimension: Mapped[str] = mapped_column(String(80), nullable=False, default="total")
    numeric_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    text_value: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(24))
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    data_quality: Mapped[str] = mapped_column(String(24), nullable=False, default="estimated")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="available", index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict | list | None] = mapped_column(JSONB)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "site_id",
            "metric_type",
            "dimension",
            "source",
            "observed_at",
            name="uq_seo_metric_snapshot_observation",
        ),
    )
