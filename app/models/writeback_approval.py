from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WritebackApproval(Base):
    """高风险资金回写的异人审批，参数指纹防止审批后偷换目标值。"""

    __tablename__ = "writeback_approvals"
    __table_args__ = (
        Index("ix_writeback_approvals_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    request_note: Mapped[str | None] = mapped_column(Text)
    decision_note: Mapped[str | None] = mapped_column(Text)

    requested_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    approved_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    consumed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime)
