from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# 人工/AI 对一次调价是否达成目的的判定
VERDICT_LABELS = {"achieved": "已达成", "missed": "未达成", "watch": "继续观察"}


class AdjustmentReview(Base):
    """调价后验证（R-10）：对一次出价调整核对调后效果，标已验证 + 判定。

    按 operation_records 的 dedup_key 关联（百度不给操作 ID，dedup_key 是其唯一键）。
    调前/后效果每次实时算（数据还在变）；本表只存人工验证状态 + AI 研判缓存。
    """

    __tablename__ = "adjustment_reviews"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(32), nullable=False)  # → operation_records.dedup_key

    status: Mapped[str] = mapped_column(String(10), default="pending", nullable=False)  # pending/verified
    verdict: Mapped[str | None] = mapped_column(String(10))  # VERDICT_LABELS（人工判定）
    note: Mapped[str | None] = mapped_column(Text)

    ai_verdict: Mapped[str | None] = mapped_column(String(10))  # AI 研判
    ai_reason: Mapped[str | None] = mapped_column(Text)
    ai_generated_at: Mapped[datetime | None] = mapped_column(DateTime)

    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "dedup_key", name="uq_adj_review_tenant_dedup"),
    )
