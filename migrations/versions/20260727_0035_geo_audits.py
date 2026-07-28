"""GEO audit runs and menu permission

Revision ID: 0035_geo_audits
Revises: 0034_keyword_dimension_reports
Create Date: 2026-07-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0035_geo_audits"
down_revision: Union[str, None] = "0034_keyword_dimension_reports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geo_audit_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="completed"),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("page_title", sa.Text(), nullable=True),
        sa.Column("page_description", sa.Text(), nullable=True),
        sa.Column("snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("findings", postgresql.JSONB(), nullable=True),
        sa.Column("advice", postgresql.JSONB(), nullable=True),
        sa.Column("advice_source", sa.String(length=20), nullable=True),
        sa.Column("json_ld", postgresql.JSONB(), nullable=True),
        sa.Column("llms_text", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_geo_audit_runs_tenant_id", "geo_audit_runs", ["tenant_id"]
    )
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE roles SET permissions = permissions || "
            "'{\"geo.diagnosis\":\"edit\"}'::jsonb "
            "WHERE name IN ('管理员', '运营')"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE roles SET permissions = permissions || "
            "'{\"geo.diagnosis\":\"view\"}'::jsonb "
            "WHERE name = '品牌方客户'"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE roles SET permissions = permissions - 'geo.diagnosis'")
    )
    op.drop_index("ix_geo_audit_runs_tenant_id", table_name="geo_audit_runs")
    op.drop_table("geo_audit_runs")
