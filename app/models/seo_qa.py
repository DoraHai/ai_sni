"""SEO question provenance, reusable facts and answer publication observations."""
from datetime import datetime
from sqlalchemy import BigInteger, String, Text, Integer, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class QaScope:
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('tenants.id', ondelete='CASCADE'), index=True)
    site_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('seo_sites.id', ondelete='CASCADE'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SeoQuestion(QaScope, Base):
    __tablename__ = 'seo_questions'
    title: Mapped[str] = mapped_column(String(300))
    fingerprint: Mapped[str] = mapped_column(String(64))
    topic: Mapped[str] = mapped_column(String(120), default='未分类')
    intent: Mapped[str] = mapped_column(String(32), default='learn')
    status: Mapped[str] = mapped_column(String(24), default='open')
    relevance: Mapped[int] = mapped_column(Integer, default=3)
    owner: Mapped[str | None] = mapped_column(String(120))
    sources: Mapped[list] = mapped_column(JSONB, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (UniqueConstraint('tenant_id', 'site_id', 'fingerprint', name='uq_seo_question_scope'),)


class SeoQaFact(QaScope, Base):
    __tablename__ = 'seo_qa_facts'
    title: Mapped[str] = mapped_column(String(240))
    statement: Mapped[str] = mapped_column(Text)
    source_name: Mapped[str] = mapped_column(String(240))
    source_url: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default='active')
    version: Mapped[int] = mapped_column(Integer, default=1)


class SeoQaAnswer(QaScope, Base):
    __tablename__ = 'seo_qa_answers'
    question_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('seo_questions.id', ondelete='CASCADE'), index=True)
    content_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('seo_content_assets.id', ondelete='CASCADE'), unique=True)
    format: Mapped[str] = mapped_column(String(24), default='short')
    fact_snapshots: Mapped[list] = mapped_column(JSONB, default=list)
    evidence_hash: Mapped[str] = mapped_column(String(64))


class SeoQaPlacement(QaScope, Base):
    __tablename__ = 'seo_qa_placements'
    answer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('seo_qa_answers.id', ondelete='CASCADE'), index=True)
    platform: Mapped[str] = mapped_column(String(24))
    question_url: Mapped[str | None] = mapped_column(Text)
    answer_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default='prepared')
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_version: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    observations: Mapped[list] = mapped_column(JSONB, default=list)
    reported_metrics: Mapped[dict | None] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (UniqueConstraint('answer_id', 'platform', 'content_version', name='uq_seo_qa_placement_version'),)

class SeoQaBatch(QaScope, Base):
    __tablename__ = 'seo_qa_batches'
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default='queued', index=True)
    items: Mapped[list] = mapped_column(JSONB, nullable=False)
    __table_args__ = (UniqueConstraint('tenant_id','site_id','actor','request_key',name='uq_seo_qa_batch_request'),)
