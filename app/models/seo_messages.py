"""Human conversations; separate from AI chat and content approval."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import BigInteger, String, Text, DateTime, ForeignKey, ForeignKeyConstraint, UniqueConstraint, CheckConstraint, Index, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class SeoContentConversation(Base):
    __tablename__ = "seo_content_conversations"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    site_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("seo_sites.id", ondelete="RESTRICT"), nullable=False)
    content_asset_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("seo_content_assets.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (UniqueConstraint("content_asset_id", name="uq_seo_conversation_content"),
                     Index("ix_seo_conversation_scope", "tenant_id", "site_id", "content_asset_id"))


class SeoConversationParticipant(Base):
    __tablename__ = "seo_conversation_participants"
    conversation_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("seo_content_conversations.id", ondelete="RESTRICT"), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    last_read_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (CheckConstraint("last_read_message_id >= 0", name="ck_seo_participant_read_cursor"),)


class SeoContentMessage(Base):
    __tablename__ = "seo_content_messages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sender_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sender_name: Mapped[str] = mapped_column(String(100), nullable=False)
    sender_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(["conversation_id", "sender_user_id"],
            ["seo_conversation_participants.conversation_id", "seo_conversation_participants.user_id"],
            name="fk_seo_message_participant", ondelete="RESTRICT"),
        UniqueConstraint("conversation_id", "sender_user_id", "request_id", name="uq_seo_message_request"),
        CheckConstraint("sender_kind IN ('customer','advisor')", name="ck_seo_message_sender_kind"),
        CheckConstraint("char_length(btrim(body)) BETWEEN 1 AND 4000", name="ck_seo_message_body"),
        Index("ix_seo_message_conversation_id", "conversation_id", "id"),
    )
