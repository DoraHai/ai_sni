"""A grant is one immutable authorization generation; regrant inserts a new row."""
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, Index, PrimaryKeyConstraint, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AdvisorTenantGrant(Base):
    __tablename__ = "advisor_tenant_grants"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_advisor_tenant_grants"),
        CheckConstraint("(grant_source = 'admin' AND granted_by IS NOT NULL) OR "
                        "(grant_source = 'backfill' AND granted_by IS NULL)",
                        name="ck_advisor_tenant_grants_source"),
        CheckConstraint("(revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason IS NULL) OR "
                        "(revoked_at IS NOT NULL AND revoked_at >= granted_at AND "
                        "revoked_by IS NOT NULL AND revoke_reason IS NOT NULL)",
                        name="ck_advisor_tenant_grants_revoke"),
        Index("uq_advisor_tenant_grants_active", "user_id", "tenant_id", unique=True,
              postgresql_where=text("revoked_at IS NULL")),
        Index("ix_advisor_tenant_grants_tenant", "tenant_id"),
        Index("ix_advisor_tenant_grants_granted_by", "granted_by"),
        Index("ix_advisor_tenant_grants_revoked_by", "revoked_by"),
        Index("ix_advisor_tenant_grants_user_history", "user_id", "granted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    granted_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))
    grant_source: Mapped[str] = mapped_column(String(16), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"))
    revoke_reason: Mapped[str | None] = mapped_column(String(80))
