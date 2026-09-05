"""SEO-owned task ledger and persistent image verification queue."""
from datetime import datetime
from sqlalchemy import BigInteger, String, DateTime, ForeignKey, CheckConstraint, Index, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class SeoTask(Base):
    __tablename__ = 'seo_tasks'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('tenants.id',ondelete='CASCADE'),nullable=False)
    site_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('seo_sites.id',ondelete='CASCADE'),nullable=False)
    module: Mapped[str] = mapped_column(String(3),nullable=False,default='seo')
    action_type: Mapped[str] = mapped_column(String(64),nullable=False)
    title: Mapped[str] = mapped_column(String(240),nullable=False)
    params: Mapped[dict] = mapped_column(JSONB,nullable=False,default=dict)
    status: Mapped[str] = mapped_column(String(16),nullable=False,default='open')
    created_by: Mapped[str] = mapped_column(String(64),nullable=False)
    assignee_role: Mapped[str] = mapped_column(String(80),nullable=False)
    completion_evidence: Mapped[dict | None] = mapped_column(JSONB)
    baseline: Mapped[dict] = mapped_column(JSONB,nullable=False,default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now(),nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now(),onupdate=func.now(),nullable=False)
    __table_args__ = (CheckConstraint("module = 'seo'",name='ck_seo_task_module'),CheckConstraint("status IN ('open','in_progress','done','cancelled')",name='ck_seo_task_status'),Index('ix_seo_task_scope','tenant_id','site_id','status'))


class SeoImageVerification(Base):
    __tablename__ = 'seo_image_verifications'
    id: Mapped[int] = mapped_column(BigInteger,primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger,ForeignKey('tenants.id',ondelete='CASCADE'),nullable=False)
    site_id: Mapped[int] = mapped_column(BigInteger,ForeignKey('seo_sites.id',ondelete='CASCADE'),nullable=False)
    page_id: Mapped[int] = mapped_column(BigInteger,ForeignKey('seo_site_pages.id',ondelete='CASCADE'),nullable=False)
    review_id: Mapped[int] = mapped_column(BigInteger,ForeignKey('seo_image_alt_reviews.id',ondelete='CASCADE'),nullable=False)
    status: Mapped[str] = mapped_column(String(20),nullable=False,default='pending')
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),nullable=False)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now())
    evidence: Mapped[dict | None] = mapped_column(JSONB)
    result_snapshot_id: Mapped[int | None] = mapped_column(BigInteger,ForeignKey('seo_page_snapshots.id',ondelete='RESTRICT'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now(),nullable=False)
    __table_args__ = (CheckConstraint("status IN ('pending','checking','verified','unverified','unavailable','superseded')",name='ck_seo_image_verification_status'),Index('ix_seo_image_verification_due','status','available_at'),Index('ix_seo_image_verification_scope','tenant_id','site_id','review_id'))
