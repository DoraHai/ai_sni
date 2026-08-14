"""关键词报表地域汇总（省级），供客户画像地域占比使用。

粒度：tenant + date + province（不下钻到 keyword/city，避免数据量爆炸）。
数据来源：关键词报表 reportType=2602783，带 provinceName 字段，按省聚合。
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class KwRegionSnapshot(Base):
    __tablename__ = "kw_region_snapshots"
    __table_args__ = (
        UniqueConstraint("tenant_id", "report_date", "province", name="uq_kw_region_snapshot"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    baidu_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("baidu_accounts.id")
    )

    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    province: Mapped[str] = mapped_column(String(50), nullable=False)

    cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    click: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    impression: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
