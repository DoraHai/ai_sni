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


class Campaign(Base):
    """推广计划维度表（CampaignService/getCampaign 同步）。

    region_price_factor / schedule_price_factors 是出价系数 4 层叠加里的
    分地域、分时段两层，原样存 JSONB，详情页系数面板接入时再解析。
    """

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    baidu_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("baidu_accounts.id")
    )

    campaign_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    campaign_name: Mapped[str | None] = mapped_column(Text)
    budget: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))  # 计划每日预算
    pause: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[int | None] = mapped_column(SmallInteger)
    equipment_type: Mapped[int | None] = mapped_column(SmallInteger)
    region_target: Mapped[list | None] = mapped_column(JSONB)
    schedule: Mapped[list | None] = mapped_column(JSONB)  # 推广暂停时段
    region_price_factor: Mapped[list | None] = mapped_column(JSONB)  # 分地域出价系数
    schedule_price_factors: Mapped[list | None] = mapped_column(JSONB)  # 分时段出价系数
    price_ratio: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))  # 移动出价比例
    negative_words: Mapped[list | None] = mapped_column(JSONB)
    exact_negative_words: Mapped[list | None] = mapped_column(JSONB)
    baidu_create_time: Mapped[datetime | None] = mapped_column(DateTime)

    synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "campaign_id", name="uq_campaigns_tenant_camp"),
    )


class Adgroup(Base):
    """推广单元维度表（AdgroupService/getAdgroup 同步）。"""

    __tablename__ = "adgroups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    baidu_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("baidu_accounts.id")
    )

    adgroup_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    campaign_id: Mapped[int | None] = mapped_column(BigInteger)
    adgroup_name: Mapped[str | None] = mapped_column(Text)
    max_price: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))  # 单元出价
    pause: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[int | None] = mapped_column(SmallInteger)
    price_ratio: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))  # 移动出价比率，≤0=继承计划
    negative_words: Mapped[list | None] = mapped_column(JSONB)
    exact_negative_words: Mapped[list | None] = mapped_column(JSONB)
    pc_final_url: Mapped[str | None] = mapped_column(Text)
    mobile_final_url: Mapped[str | None] = mapped_column(Text)
    pc_track_param: Mapped[str | None] = mapped_column(Text)
    mobile_track_param: Mapped[str | None] = mapped_column(Text)
    pc_track_template: Mapped[str | None] = mapped_column(Text)
    mobile_track_template: Mapped[str | None] = mapped_column(Text)

    synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "adgroup_id", name="uq_adgroups_tenant_adg"),
    )
