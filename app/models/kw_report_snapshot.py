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


class KwReportSnapshot(Base):
    """关键词维度报告快照（百度 OpenApiReportService.getReportData reportType=2602783）。

    一行 = 一个关键词 × 一天 × 一种设备（PC/移动）。
    upsert 键：(tenant_id, report_date, keyword_id, device)。
    raw_metrics 存原始 JSON 全量，方便后续新指标接入时不动 schema。
    """

    __tablename__ = "kw_report_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    baidu_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("baidu_accounts.id")
    )

    # ===== 维度 =====
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    campaign_id: Mapped[int | None] = mapped_column(BigInteger)
    campaign_name: Mapped[str | None] = mapped_column(Text)
    adgroup_id: Mapped[int | None] = mapped_column(BigInteger)
    adgroup_name: Mapped[str | None] = mapped_column(Text)
    keyword_id: Mapped[int | None] = mapped_column(BigInteger)
    keyword: Mapped[str | None] = mapped_column(Text)
    match_type: Mapped[int | None] = mapped_column(SmallInteger)
    device: Mapped[int | None] = mapped_column(SmallInteger)

    # ===== 效果指标 =====
    impression: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    click: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    cpc: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    ctr: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    avg_rank: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    # 转化：ocpcConversionsDetail2 电话按钮点击量（苏尔寿主转化指标，见文档 0262）
    conversions: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # ===== 质量度 & 评分 =====
    quality_enum: Mapped[int | None] = mapped_column(SmallInteger)
    estimated_click_rate: Mapped[int | None] = mapped_column(SmallInteger)
    business_relationship: Mapped[int | None] = mapped_column(SmallInteger)
    land_page_experience: Mapped[int | None] = mapped_column(SmallInteger)

    # ===== 上方位指标 =====
    top_pageviews: Mapped[int | None] = mapped_column(BigInteger)
    top_pclicks: Mapped[int | None] = mapped_column(BigInteger)
    top_pay: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    top_pv_win_a: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    top_first_pv_win_a: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))

    # ===== 出价 =====
    bid_new: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))

    # ===== 全量原始指标（兜底，方便加新指标不改表） =====
    raw_metrics: Mapped[dict | None] = mapped_column(JSONB)

    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "report_date",
            "keyword_id",
            "device",
            name="uq_kw_report_tenant_date_kw_device",
        ),
    )
