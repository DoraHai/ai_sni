"""Durable SEO AI quota and replay records."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0090_seo_ai_operations"
down_revision = "0089_seo_metric_partial_status"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "seo_ai_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", sa.BigInteger()),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("charged_on", sa.String(10), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "request_key", name="uq_seo_ai_operation_request"),
        sa.CheckConstraint("status IN ('running','succeeded','refunded')", name="ck_seo_ai_operation_status"),
    )
    op.create_index("ix_seo_ai_operation_expiry", "seo_ai_operations", ["status", "expires_at"])
    op.create_index("ix_seo_ai_operation_tenant_actor", "seo_ai_operations", ["tenant_id", "actor", "created_at"])


def downgrade():
    # Fail closed: dropping running claims would lose outstanding refunds.
    op.execute("LOCK TABLE seo_ai_operations IN ACCESS EXCLUSIVE MODE")
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM seo_ai_operations WHERE status = 'running') THEN
            RAISE EXCEPTION 'Unsettled SEO AI operations prevent downgrade';
        END IF;
    END $$""")
    op.drop_table("seo_ai_operations")
