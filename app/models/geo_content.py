from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GeoContentTask(Base):
    """GEO 内容生产任务。"""

    __tablename__ = "geo_content_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tenants.id"), nullable=False, index=True
    )
    prompt_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("geo_prompts.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    target_channels: Mapped[list | None] = mapped_column(JSONB)
    owner_user_id: Mapped[int | None] = mapped_column(BigInteger)
    brief: Mapped[dict | None] = mapped_column(JSONB)
    rule_result: Mapped[dict | None] = mapped_column(JSONB)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class GeoTaskFact(Base):
    """任务与事实卡多对多绑定。"""

    __tablename__ = "geo_task_facts"

    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("geo_content_tasks.id", ondelete="CASCADE"), primary_key=True
    )
    fact_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("geo_facts.id", ondelete="CASCADE"), primary_key=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class GeoArticleVersion(Base):
    """内容母稿版本。"""

    __tablename__ = "geo_article_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("geo_content_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="master")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str | None] = mapped_column(Text)
    outline: Mapped[dict | None] = mapped_column(JSONB)
    generation_meta: Mapped[dict | None] = mapped_column(JSONB)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class GeoChannelVariant(Base):
    """渠道适配版本。"""

    __tablename__ = "geo_channel_variants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("geo_content_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    article_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("geo_article_versions.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    export_format: Mapped[str] = mapped_column(String(16), nullable=False, default="markdown")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class GeoPublication(Base):
    """人工发布回填记录。"""

    __tablename__ = "geo_publications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    variant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("geo_channel_variants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    publish_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="manual_export")
    published_url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
