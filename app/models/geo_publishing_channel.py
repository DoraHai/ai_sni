"""Tenant-owned publishing channels and their server-side account settings."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GeoPublishingChannel(Base):
    __tablename__ = "geo_publishing_channels"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_geo_publishing_channels_tenant_name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    channel_type: Mapped[str] = mapped_column(String(32), nullable=False)
    publish_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="manual_only")
    base_url: Mapped[str | None] = mapped_column(Text)
    content_rules: Mapped[dict | None] = mapped_column(JSONB)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class GeoChannelAccount(Base):
    __tablename__ = "geo_channel_accounts"
    __table_args__ = (UniqueConstraint("channel_id", "display_name", name="uq_geo_channel_accounts_channel_name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id"), nullable=False, index=True)
    channel_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("geo_publishing_channels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    auth_type: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    credentials_encrypted: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unconfigured")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
