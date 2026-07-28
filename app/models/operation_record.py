from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# getOperationRecord 的 optLevel（文档 0915，只订阅这三层）
OPT_LEVEL_LABELS = {5: "关键词", 1: "单元", 2: "计划"}

# 订阅的操作内容 → 中文标签（文档 0914），调价台账聚焦出价/状态/系数类
OPT_CONTENT_LABELS = {
    # 关键词层
    "bidPriceWord": "关键词出价",
    "mobilePrice": "移动出价",
    "shelveWord": "暂停/启用关键词",
    "updWordMatch": "匹配模式",
    "wordStrategy": "出价策略绑定",
    # 单元层
    "bidPriceUnit": "单元出价",
    "matchPriceFactor": "分匹配出价系数",
    "devicePriceFactor": "设备出价系数",
    # 计划层
    "campaignCycPriceFactor": "分时段出价系数",
    "updateCampaignPrice": "计划设备系数",
    "priceStrategy": "出价策略",
}


class OperationRecord(Base):
    """百度后台操作记录（ToolkitService/getOperationRecord 同步，只读）。

    百度不返回记录 ID，幂等靠 dedup_key（全字段 md5）。AI 建议值/是否采纳/
    调后效果三列是平台自存字段（M2 建议引擎接入后补），本表只存百度侧事实。
    """

    __tablename__ = "operation_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    baidu_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("baidu_accounts.id")
    )

    opt_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    opt_type: Mapped[int | None] = mapped_column(SmallInteger)  # 1设置 4修改 5暂停 6启用…
    opt_level: Mapped[int | None] = mapped_column(SmallInteger)  # 5关键词 1单元 2计划
    opt_content: Mapped[str | None] = mapped_column(String(50))
    opt_obj: Mapped[str | None] = mapped_column(Text)  # 被操作对象名称（关键词/单元/计划名）
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    plan_id: Mapped[int | None] = mapped_column(BigInteger)
    unit_id: Mapped[int | None] = mapped_column(BigInteger)

    dedup_key: Mapped[str] = mapped_column(String(32), nullable=False)

    synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "dedup_key", name="uq_operation_records_tenant_dedup"),
    )
