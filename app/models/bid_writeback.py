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

# 回写台账状态
WRITEBACK_STATUS_LABELS = {
    "success": "已写回",
    "failed": "失败",
    "dry_run": "演练（未真改）",
}


class BidWriteback(Base):
    """调价回写台账：平台主动发起的出价写回（updateWord）逐条留痕。

    与 operation_records（百度侧只读同步事实）区分——本表记的是「我们发起的写动作」，
    含旧价快照、目标价、是否演练（dry_run）、百度返回与操作人，用于审计 + 回滚依据。
    dry_run=True 表示演练模式拦截、未真发百度（status=dry_run）。
    """

    __tablename__ = "bid_writebacks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    baidu_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("baidu_accounts.id")
    )
    suggestion_id: Mapped[int | None] = mapped_column(BigInteger)  # 来源建议；手动回写为 None

    keyword_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    keyword: Mapped[str | None] = mapped_column(Text)
    campaign_id: Mapped[int | None] = mapped_column(BigInteger)
    campaign_name: Mapped[str | None] = mapped_column(Text)
    adgroup_id: Mapped[int | None] = mapped_column(BigInteger)

    old_bid: Mapped[float | None] = mapped_column(Numeric(10, 2))  # 写回前快照
    new_bid: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    change_pct: Mapped[float | None] = mapped_column(Numeric(6, 2))

    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False)  # success/failed/dry_run
    baidu_response: Mapped[str | None] = mapped_column(Text)
    error_msg: Mapped[str | None] = mapped_column(Text)

    operator_user_id: Mapped[int | None] = mapped_column(BigInteger)
    operator_name: Mapped[str | None] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    executed_at: Mapped[datetime | None] = mapped_column(DateTime)
