"""baidu service-provider OAuth grants and account mappings

Revision ID: 0036_baidu_oauth
Revises: 0035_geo_audits
Create Date: 2026-07-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0036_baidu_oauth"
down_revision: Union[str, None] = "0035_geo_audits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "baidu_oauth_states",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "return_path",
            sa.String(length=300),
            nullable=False,
            server_default="/onboarding",
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("state_hash", name="uq_baidu_oauth_states_hash"),
    )
    op.create_index(
        "ix_baidu_oauth_states_expiry",
        "baidu_oauth_states",
        ["expires_at", "consumed_at"],
    )

    op.create_table(
        "baidu_oauth_grants",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.BigInteger(),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column("app_id", sa.String(length=64), nullable=False),
        sa.Column("oauth_user_id", sa.BigInteger(), nullable=False),
        sa.Column("open_id", sa.String(length=200), nullable=False),
        sa.Column("master_ucid", sa.BigInteger(), nullable=False),
        sa.Column("master_name", sa.String(length=100), nullable=False),
        sa.Column("account_type", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("refresh_expires_at", sa.DateTime(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="active"
        ),
        sa.Column(
            "authorized_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "app_id",
            "oauth_user_id",
            name="uq_baidu_oauth_grant_identity",
        ),
    )
    op.create_index(
        "ix_baidu_oauth_grants_refresh",
        "baidu_oauth_grants",
        ["status", "expires_at"],
    )

    op.add_column(
        "baidu_accounts",
        sa.Column(
            "oauth_grant_id",
            sa.BigInteger(),
            sa.ForeignKey("baidu_oauth_grants.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "baidu_accounts",
        sa.Column(
            "account_role",
            sa.String(length=20),
            nullable=False,
            server_default="standalone",
        ),
    )
    op.add_column(
        "baidu_accounts",
        sa.Column("refresh_expires_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "baidu_accounts",
        sa.Column("authorized_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "baidu_accounts",
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_baidu_accounts_oauth_grant_id",
        "baidu_accounts",
        ["oauth_grant_id"],
    )
    op.create_unique_constraint(
        "uq_baidu_accounts_tenant_ucid",
        "baidu_accounts",
        ["tenant_id", "baidu_ucid"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_baidu_accounts_tenant_ucid", "baidu_accounts", type_="unique"
    )
    op.drop_index("ix_baidu_accounts_oauth_grant_id", table_name="baidu_accounts")
    op.drop_column("baidu_accounts", "last_synced_at")
    op.drop_column("baidu_accounts", "authorized_at")
    op.drop_column("baidu_accounts", "refresh_expires_at")
    op.drop_column("baidu_accounts", "account_role")
    op.drop_column("baidu_accounts", "oauth_grant_id")
    op.drop_index("ix_baidu_oauth_grants_refresh", table_name="baidu_oauth_grants")
    op.drop_table("baidu_oauth_grants")
    op.drop_index("ix_baidu_oauth_states_expiry", table_name="baidu_oauth_states")
    op.drop_table("baidu_oauth_states")
