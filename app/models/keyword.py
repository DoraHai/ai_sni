from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
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

# 5 类分级（业务规则之首）。longtail 只能人工标，自动分类不产出
CATEGORY_LABELS = {
    "brand": "品牌词",
    "focus": "重点词",
    "normal": "一般词",
    "longtail": "长尾精准词",
    "new": "新词",
}


class Keyword(Base):
    """关键词维度表（KeywordService/getWord 同步 + 5 类分级）。

    v1 范围：只覆盖在 kw_report_snapshots 出现过的关键词（按 keyword_id 反查百度）。
    零展现的长尾精准词拿不到——等 campaign/adgroup 层级同步做全量枚举后补齐。
    分级：category_source='manual' 的行自动分类永不覆盖。
    """

    __tablename__ = "keywords"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    baidu_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("baidu_accounts.id")
    )

    # ===== 百度侧维度（getWord） =====
    keyword_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    keyword: Mapped[str | None] = mapped_column(Text)
    campaign_id: Mapped[int | None] = mapped_column(BigInteger)
    adgroup_id: Mapped[int | None] = mapped_column(BigInteger)
    match_type: Mapped[int | None] = mapped_column(SmallInteger)
    phrase_type: Mapped[int | None] = mapped_column(SmallInteger)
    price: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))  # 真实当前出价
    pause: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[int | None] = mapped_column(SmallInteger)
    tabs: Mapped[list | None] = mapped_column(JSONB)  # 物料标签数组，31=重点关键词
    quality: Mapped[int | None] = mapped_column(SmallInteger)
    # 百度官方指导价（getWord leftPriceGuide/mPriceGuide，[0,999.99)，数据不足为空）
    # AI 调价建议的外部锚点：当前价低于指导=有空间、高于=偏贵
    left_price_guide: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))  # 计算机
    m_price_guide: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))  # 移动
    baidu_create_time: Mapped[datetime | None] = mapped_column(DateTime)

    # ===== 本地维度 =====
    first_seen_date: Mapped[date | None] = mapped_column(Date)  # 报告中首次出现
    total_impression: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # ===== 5 类分级 =====
    category: Mapped[str | None] = mapped_column(String(10))  # CATEGORY_LABELS 的 key
    category_source: Mapped[str] = mapped_column(
        String(10), default="auto", nullable=False
    )  # auto | manual
    category_updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "keyword_id", name="uq_keywords_tenant_kw"),
    )
