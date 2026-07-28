"""initial schema: tenants, baidu_accounts, api_audit_logs

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-09

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("strategy", sa.String(length=20), nullable=True),
        sa.Column("monthly_budget", sa.DECIMAL(precision=12, scale=2), nullable=True),
        sa.Column("contract_start", sa.Date(), nullable=True),
        sa.Column("contract_end", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "baidu_accounts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column("baidu_username", sa.String(length=100), nullable=False),
        sa.Column("baidu_ucid", sa.BigInteger(), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("auth_mode", sa.String(length=20), nullable=False, server_default="self"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_baidu_accounts_tenant_status",
        "baidu_accounts",
        ["tenant_id", "status"],
    )

    op.create_table(
        "api_audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=True),
        sa.Column("endpoint", sa.String(length=200), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_api_audit_logs_tenant_created", "api_audit_logs", ["tenant_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_api_audit_logs_tenant_created", table_name="api_audit_logs")
    op.drop_table("api_audit_logs")
    op.drop_index("ix_baidu_accounts_tenant_status", table_name="baidu_accounts")
    op.drop_table("baidu_accounts")
    op.drop_table("tenants")
