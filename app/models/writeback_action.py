from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# 非出价类写回动作（出价回写见 bid_writebacks）
WRITEBACK_ACTION_LABELS = {
    "negative": "加否词",
    "add_word": "转拓词",
    "remove_negative": "删否词",
    "pause": "暂停",
    "enable": "启用",
    "set_match_type": "改匹配模式",
    "set_account_budget": "改账户日预算",
    "set_campaign_budget": "改计划日预算",
    "set_campaign_region": "改计划投放地域",
    "campaign_pause": "暂停计划",
    "campaign_enable": "启用计划",
    "campaign_schedule": "改计划投放时段",
    "adgroup_pause": "暂停单元",
    "adgroup_enable": "启用单元",
    "set_adgroup_bid": "改单元出价",
    "set_adgroup_url": "改单元落地页",
    "build_campaign": "智能搭建计划",
    "build_adgroup": "智能搭建单元",
    "build_keyword": "智能搭建关键词",
    "build_creative": "智能搭建创意",
}
WB_ACTION_STATUS_LABELS = {
    "success": "已执行",
    "failed": "失败",
    "dry_run": "待回写（演练记录）",
    "pending": "执行结果待确认",
    "reconcile": "待人工对账",
}
MATCH_MODE_LABELS = {"exact": "精确", "phrase": "短语"}


class WritebackAction(Base):
    """非出价类写回台账：加否词（updateAdgroup 追加否词）、转拓词（addWord 加关键词）。

    与 bid_writebacks（出价回写专用）区分。同样经 dry-run 安全网：演练时记台账不真发。
    """

    __tablename__ = "writeback_actions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    baidu_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("baidu_accounts.id")
    )
    approval_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("writeback_approvals.id")
    )

    action_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 见 WRITEBACK_ACTION_LABELS
    word: Mapped[str] = mapped_column(Text, nullable=False)  # 否词 / 拓词（来自搜索词）；预算类写回存对象名
    match_mode: Mapped[str | None] = mapped_column(String(10))  # exact / phrase
    price: Mapped[float | None] = mapped_column(Numeric(10, 2))  # 转拓词出价
    # 通用数值前后快照（账户日预算/将来计划预算等数值类写回用：old→new）
    old_value: Mapped[float | None] = mapped_column(Numeric(12, 2))
    new_value: Mapped[float | None] = mapped_column(Numeric(12, 2))

    campaign_id: Mapped[int | None] = mapped_column(BigInteger)
    campaign_name: Mapped[str | None] = mapped_column(Text)
    adgroup_id: Mapped[int | None] = mapped_column(BigInteger)
    adgroup_name: Mapped[str | None] = mapped_column(Text)

    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False)  # success/failed/dry_run/pending/reconcile
    baidu_response: Mapped[str | None] = mapped_column(Text)
    error_msg: Mapped[str | None] = mapped_column(Text)

    reconciliation_result: Mapped[str | None] = mapped_column(String(32))
    reconciliation_note: Mapped[str | None] = mapped_column(Text)
    reconciled_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime)

    operator_user_id: Mapped[int | None] = mapped_column(BigInteger)
    operator_name: Mapped[str | None] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    executed_at: Mapped[datetime | None] = mapped_column(DateTime)
