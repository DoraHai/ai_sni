"""SEM-only tasks; no relationship to approval consumption or ad execution."""
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SemTask(Base):
    __tablename__ = "sem_tasks"
    __table_args__ = (
        CheckConstraint("module = 'sem'", name="ck_sem_tasks_module"),
        CheckConstraint("action_type = 'metric_target'", name="ck_sem_tasks_action"),
        CheckConstraint("status IN ('open','in_progress','done','cancelled')", name="ck_sem_tasks_status"),
        CheckConstraint("assignee_role IN ('operator','admin')", name="ck_sem_tasks_role"),
        CheckConstraint("jsonb_typeof(params) = 'object'", name="ck_sem_tasks_params"),
        CheckConstraint("jsonb_typeof(baseline_snapshot) = 'object'", name="ck_sem_tasks_baseline"),
        CheckConstraint("completion_evidence IS NULL OR jsonb_typeof(completion_evidence) = 'object'", name="ck_sem_tasks_evidence"),
        CheckConstraint("(status = 'done' AND completion_evidence IS NOT NULL) OR (status <> 'done' AND completion_evidence IS NULL)", name="ck_sem_tasks_done"),
        Index("ix_sem_tasks_queue", "tenant_id", "status", "id"),
        Index("ix_sem_tasks_action", "tenant_id", "action_type", "id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    module: Mapped[str] = mapped_column(String(8), nullable=False, default="sem")
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_by: Mapped[str] = mapped_column(String(80), nullable=False)
    assignee_role: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    completion_evidence: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
