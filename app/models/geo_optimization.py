"""GEO 三级优化结构：优化业务 → 优化单元（关键词）→ 优化意图词(geo_prompts)。"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GeoOptimizationBusiness(Base):
    """优化业务（客户业务线 / 产品线）。"""

    __tablename__ = "geo_optimization_businesses"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_geo_opt_business_tenant_name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class GeoOptimizationUnit(Base):
    """优化单元（关键词 / 主题单元），挂在优化业务下。"""

    __tablename__ = "geo_optimization_units"
    __table_args__ = (
        UniqueConstraint("tenant_id", "business_id", "name", name="uq_geo_opt_unit_biz_name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    business_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("geo_optimization_businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    keyword: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class GeoDailyMetric(Base):
    """按天汇总指标（品牌提及率 / 点名认知 / AI 引用等）。"""

    __tablename__ = "geo_daily_metrics"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "metric_date",
            "scope_key",
            name="uq_geo_daily_metric_scope",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    metric_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # 维度键：t=租户 / b{id}=业务 / u{id}=单元 / e{engine} 组合，避免 NULL 唯一约束问题
    scope_key: Mapped[str] = mapped_column(String(80), nullable=False, default="t")
    business_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    unit_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    engine: Mapped[str | None] = mapped_column(String(64))

    snapshots_visibility: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshots_probe: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    brand_mentions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    brand_probe_hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    top1_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 口径：独立被引域名数 / 引用 URL 出现总次数（快照 cited_urls 聚合）
    distinct_cited_domains: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    citation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    brand_mention_rate: Mapped[float | None] = mapped_column(Float)
    brand_probe_recognition_rate: Mapped[float | None] = mapped_column(Float)
    top1_rate: Mapped[float | None] = mapped_column(Float)
    # 竞品：可见性样本中提及次数 / 率（top N 写入 JSON）
    competitor_mentions: Mapped[dict | None] = mapped_column(JSONB)
    top_competitor: Mapped[str | None] = mapped_column(String(80))
    top_competitor_rate: Mapped[float | None] = mapped_column(Float)
    any_competitor_mentions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
