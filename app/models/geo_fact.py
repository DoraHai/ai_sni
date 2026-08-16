from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GeoFact(Base):
    """品牌事实卡：生成内容的唯一可信证据来源。"""

    __tablename__ = "geo_facts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    business_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("geo_optimization_businesses.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    fact_type: Mapped[str] = mapped_column(String(32), nullable=False, default="product")
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[date | None] = mapped_column(Date)
    expires_at: Mapped[date | None] = mapped_column(Date)
    trust_level: Mapped[str] = mapped_column(String(16), nullable=False, default="needs_review")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    meta: Mapped[dict | None] = mapped_column(JSONB)
    author_name: Mapped[str | None] = mapped_column(String(100))
    import_batch_id: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
