from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class KeywordRegionReport(Base):
    """关键词地域维度效果快照。

    百度关键词报告地域字段不支持 HOUR，所以地域数据按天落库。
    """

    __tablename__ = "keyword_region_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    baidu_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("baidu_accounts.id")
    )

    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    campaign_id: Mapped[int | None] = mapped_column(BigInteger)
    campaign_name: Mapped[str | None] = mapped_column(Text)
    adgroup_id: Mapped[int | None] = mapped_column(BigInteger)
    adgroup_name: Mapped[str | None] = mapped_column(Text)
    keyword_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    keyword: Mapped[str | None] = mapped_column(Text)
    device: Mapped[int | None] = mapped_column(SmallInteger)
    region_name: Mapped[str] = mapped_column(Text, nullable=False)
    region_level: Mapped[str] = mapped_column(Text, nullable=False, default="city")

    impression: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    click: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    cpc: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    ctr: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))

    raw_metrics: Mapped[dict | None] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "report_date",
            "keyword_id",
            "region_name",
            "region_level",
            "device",
            name="uq_kw_region_report_tenant_date_kw_region_device",
        ),
    )


class KeywordHourlyReport(Base):
    """关键词小时维度效果快照。"""

    __tablename__ = "keyword_hourly_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    baidu_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("baidu_accounts.id")
    )

    report_datetime: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    hour: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    campaign_id: Mapped[int | None] = mapped_column(BigInteger)
    campaign_name: Mapped[str | None] = mapped_column(Text)
    adgroup_id: Mapped[int | None] = mapped_column(BigInteger)
    adgroup_name: Mapped[str | None] = mapped_column(Text)
    keyword_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    keyword: Mapped[str | None] = mapped_column(Text)
    device: Mapped[int | None] = mapped_column(SmallInteger)

    impression: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    click: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    cpc: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    ctr: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))

    raw_metrics: Mapped[dict | None] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "report_datetime",
            "keyword_id",
            "device",
            name="uq_kw_hourly_report_tenant_dt_kw_device",
        ),
    )
