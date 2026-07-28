from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# 线索状态流转（销售跟进）
LEAD_STATUS_LABELS = {
    "new": "新建",
    "following": "跟进中",
    "won": "已成交",
    "invalid": "无效",
}
# 意向等级（录入时人工判断，可空）
LEAD_INTENT_LABELS = {"high": "高", "mid": "中", "low": "低"}
# 来源渠道：阶段一只有手动录入，留口给以后百度埋码/爱番番自动接入
LEAD_SOURCE_LABELS = {"manual": "手动录入", "baidu": "百度转化", "aifanfan": "爱番番"}


class Lead(Base):
    """客户真线索台账（手动录入起步）。

    百度埋码转化（ocpcConversionsDetail2 电话点击等）是代理指标、粗；真线索质量/成交在
    客户自己的销售台账里。本表让客户把真线索录进来，和消费/点击对齐，算真实线索成本与 ROI，
    也是产品三层 L1 小白模式的数据地基。归因到账户/计划级（campaign_id 可空=账户级）。
    """

    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)

    contact_name: Mapped[str | None] = mapped_column(String(100))  # 姓名/称呼
    phone: Mapped[str | None] = mapped_column(String(50))  # 电话 / 微信 / QQ 等联系方式

    source_channel: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    external_id: Mapped[str | None] = mapped_column(String(64))  # 百度 clueId，手动录入为空（幂等去重）
    campaign_id: Mapped[int | None] = mapped_column(BigInteger)  # 归因计划，空=账户级
    campaign_name: Mapped[str | None] = mapped_column(Text)
    keyword: Mapped[str | None] = mapped_column(Text)  # 触发关键词（百度线索带，词级归因）
    connect: Mapped[int | None] = mapped_column(SmallInteger)  # 电话接通：1接通/0未接通/None

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    intent_level: Mapped[str | None] = mapped_column(String(10))  # high/mid/low
    deal_amount: Mapped[float | None] = mapped_column(Numeric(12, 2))  # 成交金额

    lead_time: Mapped[date | None] = mapped_column(Date)  # 线索发生日期（客户填）
    note: Mapped[str | None] = mapped_column(Text)

    operator_user_id: Mapped[int | None] = mapped_column(BigInteger)
    operator_name: Mapped[str | None] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())
