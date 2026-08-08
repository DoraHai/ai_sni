"""GEO stage: task review fields + channel registry readiness."""

from alembic import op
import sqlalchemy as sa

revision = "0047_geo_review_channels"
down_revision = "0046_geo_action_tickets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "geo_content_tasks",
        sa.Column(
            "review_status",
            sa.String(length=20),
            nullable=False,
            server_default="none",
        ),
    )
    op.add_column(
        "geo_content_tasks",
        sa.Column("review_note", sa.Text(), nullable=True),
    )
    op.add_column(
        "geo_content_tasks",
        sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "geo_content_tasks",
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_geo_content_tasks_tenant_review",
        "geo_content_tasks",
        ["tenant_id", "review_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_geo_content_tasks_tenant_review", table_name="geo_content_tasks")
    op.drop_column("geo_content_tasks", "reviewed_at")
    op.drop_column("geo_content_tasks", "reviewed_by")
    op.drop_column("geo_content_tasks", "review_note")
    op.drop_column("geo_content_tasks", "review_status")
