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
    competitors: Mapped[list | None] = mapped_column(JSONB)
    brand_position: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    sentiment: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    # linked | plaintext | mixed | none | unknown
    citation_format: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    # accurate | partial | inaccurate | unknown
    citation_accuracy: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    # 巡检追溯：NULL=人工粘贴/单次探测落库
    patrol_run_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("geo_visibility_patrol_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # manual | openai_compat | mock_persona | unknown
    sample_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    # True = 人设模拟样本，报表须标注，不可当真实引擎效果
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 引用 URL 反查 geo_publications 命中的 publication id 列表
    matched_publication_ids: Mapped[list | None] = mapped_column(JSONB)
    # 归属优化期次（可空；关闭期次后仍保留以回看）
    period_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("geo_optimization_periods.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
