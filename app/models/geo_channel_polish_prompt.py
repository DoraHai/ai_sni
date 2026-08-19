from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GeoChannelPolishPrompt(Base):
    """租户级渠道成稿提示词覆盖。

    channel_key='__system__' 行存共享 system_prompt；
    其余行存各渠道 voice_prompt / min_body_chars。
    字段为 null 表示使用代码默认。
    """

    __tablename__ = "geo_channel_polish_prompts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "channel_key", name="uq_geo_channel_polish_prompts"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    channel_key: Mapped[str] = mapped_column(String(32), nullable=False)
    system_prompt: Mapped[str | None] = mapped_column(Text)
    voice_prompt: Mapped[str | None] = mapped_column(Text)
    min_body_chars: Mapped[int | None] = mapped_column(Integer)
    updated_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
