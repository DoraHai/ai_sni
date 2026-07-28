from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
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

TARGET_RANK_LABELS = {0: "上方位首位", 1: "上方位"}


class PriceStrategy(Base):
    """优化排名出价策略（PriceStrategyService/getPriceStrategy 同步）。

    出价系数 4 层叠加里的"优化排名策略系数"层：priceFactor 是加价上限
    （范围 1.01~10，竞价抢不到 targetRank 时百度最多加到 基础出价 × priceFactor）。
    注意 isPause 语义反直觉：true=关闭，false/默认=开启（文档 0300）。
    """

    __tablename__ = "price_strategies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    baidu_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("baidu_accounts.id")
    )

    strategy_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    strategy_name: Mapped[str | None] = mapped_column(Text)
    strategy_type: Mapped[int | None] = mapped_column(SmallInteger)  # 0=优化排名
    target_rank: Mapped[int | None] = mapped_column(SmallInteger)  # TARGET_RANK_LABELS
    price_factor: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))  # 加价上限
    is_pause: Mapped[bool | None] = mapped_column(Boolean)  # true=关闭
    # priceStrategyCampaignTypes 原样存：[{campaignId, campaignName, isDelete, ...}]
    campaign_bindings: Mapped[list | None] = mapped_column(JSONB)

    synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "strategy_id", name="uq_price_strategies_tenant_strat"),
    )

    def bound_campaign_ids(self) -> set[int]:
        return {
            b.get("campaignId")
            for b in (self.campaign_bindings or [])
            if b.get("campaignId") is not None and not b.get("isDelete")
        }
