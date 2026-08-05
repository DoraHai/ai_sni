"""GEO period-diff: persist expand candidate runs."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0050_geo_expand_runs"
down_revision = "0049_geo_demo_statement_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_expand_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("market", sa.String(length=16), nullable=False, server_default="cn"),
        sa.Column("roots", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("items", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_geo_expand_runs_tenant_id", "geo_expand_runs", ["tenant_id"])
    op.create_index(
        "ix_geo_expand_runs_tenant_created",
        "geo_expand_runs",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_geo_expand_runs_tenant_created", table_name="geo_expand_runs")
    op.drop_index("ix_geo_expand_runs_tenant_id", table_name="geo_expand_runs")
    op.drop_table("geo_expand_runs")
