"""map each OAuth account to its own tenant and track sync status

Revision ID: 0038_oauth_account_tenants
Revises: 0037_analysis_reports
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0038_oauth_account_tenants"
down_revision: Union[str, None] = "0037_analysis_reports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenants", sa.Column("baidu_ucid", sa.BigInteger(), nullable=True)
    )
    op.create_unique_constraint(
        "uq_tenants_baidu_ucid", "tenants", ["baidu_ucid"]
    )
    op.add_column(
        "baidu_accounts",
        sa.Column(
            "sync_status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column(
        "baidu_accounts", sa.Column("last_sync_error", sa.Text(), nullable=True)
    )
    op.execute(
        "UPDATE baidu_accounts SET sync_status = "
        "CASE WHEN last_synced_at IS NULL THEN 'pending' ELSE 'synced' END"
    )

    # 0036 初版曾把 OAuth 账号挂到“发起授权时选中的客户”。这里为每个 UCID
    # 创建独立客户，并把最新一条账号关系及其已同步数据迁移过去。
    op.execute(
        """
        INSERT INTO tenants (name, strategy, brand_terms, baidu_ucid)
        SELECT latest.baidu_username, 'lead',
               jsonb_build_array(latest.baidu_username), latest.baidu_ucid
        FROM (
            SELECT DISTINCT ON (baidu_ucid)
                   baidu_username, baidu_ucid
            FROM baidu_accounts
            WHERE auth_mode = 'oauth'
            ORDER BY baidu_ucid, updated_at DESC NULLS LAST, id DESC
        ) AS latest
        ON CONFLICT (baidu_ucid) DO NOTHING
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT id, baidu_ucid,
                   row_number() OVER (
                       PARTITION BY baidu_ucid
                       ORDER BY updated_at DESC NULLS LAST, id DESC
                   ) AS rn
            FROM baidu_accounts
            WHERE auth_mode = 'oauth'
        )
        UPDATE baidu_accounts AS account
        SET tenant_id = tenant.id,
            status = 'active',
            sync_status = 'pending',
            last_sync_error = NULL
        FROM ranked
        JOIN tenants AS tenant ON tenant.baidu_ucid = ranked.baidu_ucid
        WHERE account.id = ranked.id AND ranked.rn = 1
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY baidu_ucid
                       ORDER BY updated_at DESC NULLS LAST, id DESC
                   ) AS rn
            FROM baidu_accounts
            WHERE auth_mode = 'oauth'
        )
        UPDATE baidu_accounts AS account
        SET status = 'inactive', sync_status = 'pending'
        FROM ranked
        WHERE account.id = ranked.id AND ranked.rn > 1
        """
    )

    data_tables = (
        "kw_report_snapshots",
        "keyword_region_reports",
        "keyword_hourly_reports",
        "campaigns",
        "adgroups",
        "keywords",
        "keyword_candidates",
        "price_strategies",
        "ocpc_packages",
        "operation_records",
        "search_term_reports",
        "bid_writebacks",
        "writeback_actions",
    )
    # 把最新账号关系已经落库的业务数据迁移到新客户。
    for table_name in data_tables:
        op.execute(
            sa.text(
                f"""
                UPDATE {table_name} AS data
                SET tenant_id = account.tenant_id
                FROM baidu_accounts AS account
                WHERE data.baidu_account_id = account.id
                  AND account.auth_mode = 'oauth'
                  AND account.status = 'active'
                """
            )
        )

    # 0036 期间同一 UCID 被重复授权到两个旧客户，产生了完全重复的只读同步数据。
    # 精确清理非最新的 OAuth 账号副本及其数据，避免旧客户看板继续混入新账号数据。
    for table_name in data_tables:
        op.execute(
            sa.text(
                f"""
                WITH duplicate_accounts AS (
                    SELECT id
                    FROM (
                        SELECT id,
                               row_number() OVER (
                                   PARTITION BY baidu_ucid
                                   ORDER BY updated_at DESC NULLS LAST, id DESC
                               ) AS rn
                        FROM baidu_accounts
                        WHERE auth_mode = 'oauth'
                    ) AS ranked
                    WHERE ranked.rn > 1
                )
                DELETE FROM {table_name} AS data
                USING duplicate_accounts
                WHERE data.baidu_account_id = duplicate_accounts.id
                """
            )
        )

    op.execute(
        """
        WITH duplicate_accounts AS (
            SELECT id
            FROM (
                SELECT id,
                       row_number() OVER (
                           PARTITION BY baidu_ucid
                           ORDER BY updated_at DESC NULLS LAST, id DESC
                       ) AS rn
                FROM baidu_accounts
                WHERE auth_mode = 'oauth'
            ) AS ranked
            WHERE ranked.rn > 1
        )
        DELETE FROM baidu_accounts AS account
        USING duplicate_accounts
        WHERE account.id = duplicate_accounts.id
        """
    )

    op.execute(
        """
        UPDATE baidu_oauth_grants AS oauth_grant
        SET tenant_id = linked.tenant_id
        FROM (
            SELECT oauth_grant_id, min(tenant_id) AS tenant_id
            FROM baidu_accounts
            WHERE auth_mode = 'oauth' AND status = 'active'
              AND oauth_grant_id IS NOT NULL
            GROUP BY oauth_grant_id
        ) AS linked
        WHERE oauth_grant.id = linked.oauth_grant_id
        """
    )
    op.execute(
        """
        UPDATE baidu_oauth_grants AS oauth_grant
        SET status = 'inactive'
        WHERE NOT EXISTS (
            SELECT 1 FROM baidu_accounts AS account
            WHERE account.oauth_grant_id = oauth_grant.id
              AND account.status = 'active'
        )
        """
    )


def downgrade() -> None:
    op.drop_column("baidu_accounts", "last_sync_error")
    op.drop_column("baidu_accounts", "sync_status")
    op.drop_constraint("uq_tenants_baidu_ucid", "tenants", type_="unique")
    op.drop_column("tenants", "baidu_ucid")
