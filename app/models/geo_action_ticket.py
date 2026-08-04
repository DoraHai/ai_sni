from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GeoActionTicket(Base):
    """GEO 整改验收工单（D3 · GeoLook verify 适配）。"""

    __tablename__ = "geo_action_tickets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    audit_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("geo_audit_runs.id"), nullable=True, index=True
    )
    advice_code: Mapped[str | None] = mapped_column(String(64))
    content_task_id: Mapped[int | None] = mapped_column(BigInteger)
    media_placement_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("geo_media_placements.id"), nullable=True
    )
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    action: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="todo")
    acceptance_type: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    acceptance_check: Mapped[str | None] = mapped_column(String(128))
    acceptance_desc: Mapped[str | None] = mapped_column(Text)
    baseline_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    progress_first: Mapped[dict | None] = mapped_column(JSONB)
    progress: Mapped[dict | None] = mapped_column(JSONB)
    evidence: Mapped[list | None] = mapped_column(JSONB)
    last_verify_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_verdict: Mapped[str | None] = mapped_column(String(16))
    last_note: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
