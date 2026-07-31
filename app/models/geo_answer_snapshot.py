from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GeoAnswerSnapshot(Base):
    """人工粘贴的 AI 回答快照：用于可见度对照（Wave B）。"""

    __tablename__ = "geo_answer_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    prompt_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("geo_prompts.id"), nullable=False, index=True
    )
    engine: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    mentions_brand: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cited_urls: Mapped[list | None] = mapped_column(JSONB)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
