"""Human content conversations. Production execution is separately approved.

Revision: 0106_seo_content_messages; parent: 0105_seo_content_confirmations.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0106_seo_content_messages"
down_revision = "0105_seo_content_confirmations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("seo_content_conversations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("seo_sites.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("content_asset_id", sa.BigInteger(), sa.ForeignKey("seo_content_assets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("content_asset_id", name="uq_seo_conversation_content"))
    op.create_index("ix_seo_conversation_scope", "seo_content_conversations", ["tenant_id", "site_id", "content_asset_id"])
    op.create_table("seo_conversation_participants",
        sa.Column("conversation_id", sa.BigInteger(), sa.ForeignKey("seo_content_conversations.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("last_read_message_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("last_read_message_id >= 0", name="ck_seo_participant_read_cursor"))
    op.create_table("seo_content_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("sender_user_id", sa.BigInteger(), nullable=False),
        sa.Column("sender_name", sa.String(100), nullable=False),
        sa.Column("sender_kind", sa.String(16), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["conversation_id", "sender_user_id"],
            ["seo_conversation_participants.conversation_id", "seo_conversation_participants.user_id"],
            name="fk_seo_message_participant", ondelete="RESTRICT"),
        sa.UniqueConstraint("conversation_id", "sender_user_id", "request_id", name="uq_seo_message_request"),
        sa.CheckConstraint("sender_kind IN ('customer','advisor')", name="ck_seo_message_sender_kind"),
        sa.CheckConstraint("char_length(btrim(body)) BETWEEN 1 AND 4000", name="ck_seo_message_body"))
    op.create_index("ix_seo_message_conversation_id", "seo_content_messages", ["conversation_id", "id"])
    op.execute("""CREATE FUNCTION seo_reject_message_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'SEO human messages are append only' USING ERRCODE='23514'; END; $$""")
    op.execute("""CREATE TRIGGER trg_seo_messages_append_only BEFORE UPDATE OR DELETE ON seo_content_messages
        FOR EACH ROW EXECUTE FUNCTION seo_reject_message_mutation()""")
    op.execute("""CREATE TRIGGER trg_seo_messages_no_truncate BEFORE TRUNCATE ON seo_content_messages
        FOR EACH STATEMENT EXECUTE FUNCTION seo_reject_message_mutation()""")


def downgrade():
    op.drop_table("seo_content_messages")
    op.execute("DROP FUNCTION seo_reject_message_mutation()")
    op.drop_table("seo_conversation_participants")
    op.drop_table("seo_content_conversations")
