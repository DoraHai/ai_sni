"""Shared SEO/GEO inbox schema. SEO owns the sole 0110 migration."""
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class DistributionInboxDevice(Base):
    __tablename__ = 'distribution_inbox_devices'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pairing_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    pairing_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claim_request_id: Mapped[str | None] = mapped_column(String(36))
    credential_digest: Mapped[str | None] = mapped_column(String(64))
    credential_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rate_buckets: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    __table_args__ = (
        CheckConstraint("state IN ('pending','active','revoked','expired')", name='ck_inbox_device_state'),
        CheckConstraint('revision >= 0', name='ck_inbox_device_revision'),
        Index('ix_inbox_devices_owner', 'owner_user_id', 'state'),
    )


class DistributionInboxReceipt(Base):
    __tablename__ = 'distribution_inbox_receipts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    device_id: Mapped[str] = mapped_column(String(36), ForeignKey('distribution_inbox_devices.id', ondelete='RESTRICT'), nullable=False)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    attempt_id: Mapped[str | None] = mapped_column(String(36))
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    platform: Mapped[str | None] = mapped_column(String(60))
    title: Mapped[str | None] = mapped_column(String(300))
    reported_account: Mapped[str | None] = mapped_column(String(60))
    result: Mapped[str | None] = mapped_column(String(24))
    reason_code: Mapped[str | None] = mapped_column(String(32))
    public_url: Mapped[str | None] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    url_hash: Mapped[str | None] = mapped_column(String(64))
    normalizer_version: Mapped[str | None] = mapped_column(String(16))
    content_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default='pending')
    label_state: Mapped[str] = mapped_column(String(16), nullable=False, default='pending')
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tenant_id: Mapped[int | None] = mapped_column(BigInteger)
    module: Mapped[str | None] = mapped_column(String(8))
    scope_id: Mapped[int | None] = mapped_column(BigInteger)
    article_id: Mapped[int | None] = mapped_column(BigInteger)
    article_version: Mapped[int | None] = mapped_column(Integer)
    article_digest: Mapped[str | None] = mapped_column(String(64))
    published_account: Mapped[str | None] = mapped_column(String(60))
    verification_status: Mapped[str] = mapped_column(String(16), nullable=False, default='unlinked')
    history: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint('device_id', 'event_id', name='uq_inbox_device_event'),
        CheckConstraint("state IN ('pending','active','archived','deleted')", name='ck_inbox_receipt_state'),
        CheckConstraint("label_state IN ('pending','active','revoked')", name='ck_inbox_label_state'),
        CheckConstraint('revision >= 0 AND content_bytes >= 0', name='ck_inbox_receipt_size'),
        CheckConstraint("(label_state = 'active' AND state = 'active' AND tenant_id IS NOT NULL AND module IN ('seo','geo')) OR (label_state <> 'active' AND tenant_id IS NULL AND module IS NULL AND scope_id IS NULL AND article_id IS NULL)", name='ck_inbox_assignment'),
        Index('ix_inbox_receipts_owner_state', 'owner_user_id', 'state'),
        Index('ix_inbox_receipts_target', 'tenant_id', 'module', 'scope_id'),
        Index('ix_inbox_receipts_owner_url', 'owner_user_id', 'url_hash'),
        Index('uq_inbox_active_link', 'tenant_id', 'module', text('COALESCE(scope_id, 0)'), 'url_hash', unique=True,
              postgresql_where=text("label_state = 'active' AND result = 'success' AND url_hash IS NOT NULL")),
    )
