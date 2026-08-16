from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GeoDeliverableArchive(Base):
    """交付摘要存档：生成即存，可回看与分享 token。"""

    __tablename__ = "geo_deliverable_archives"
    __table_args__ = (UniqueConstraint("share_token", name="uq_geo_deliverable_share_token"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(String(200))
    period_from: Mapped[datetime | None] = mapped_column(DateTime)
    period_to: Mapped[datetime | None] = mapped_column(DateTime)
    pack_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    markdown: Mapped[str | None] = mapped_column(Text)
    share_token: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
