"""ocpc_packages 表（oCPC 出价策略只读同步）+ 给内置角色补 manage.ocpc 菜单权限

Revision ID: 0028_ocpc_packages
Revises: 0027_assistant_messages
Create Date: 2026-06-28

OCPC 投放管理第一步（查看层）：落 OcpcService/getTargetPackageList 拉到的目标转化包——
目标转化出价 ocpcBid、学习状态 packageStatus、绑定计划 scope、转化口径 dataFlowData
（决定百度算法看不看得到电话转化）。本表只读同步，调价写回后续单独做。新菜单 manage.ocpc
（分组「投放管理」）需给内置角色（管理员/运营）补 edit，否则管理员都进不去。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0028_ocpc_packages"
down_revision: Union[str, None] = "0027_assistant_messages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ocpc_packages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("baidu_account_id", sa.BigInteger(), sa.ForeignKey("baidu_accounts.id")),
        sa.Column("package_id", sa.BigInteger(), nullable=False),
        sa.Column("package_name", sa.Text()),
        sa.Column("ocpc_bid_type", sa.SmallInteger()),
        sa.Column("ocpc_bid", sa.Numeric(10, 2)),
        sa.Column("package_status", sa.SmallInteger()),
        sa.Column("ocpc_deep_cpa", sa.Numeric(10, 2)),
        sa.Column("deep_trans_type_mode", sa.SmallInteger()),
        sa.Column("scope", JSONB()),
        sa.Column("data_flow_data", JSONB()),
        sa.Column("assist_trans_types", JSONB()),
        sa.Column("raw", JSONB()),
        sa.Column("synced_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "package_id", name="uq_ocpc_packages_tenant_pkg"),
    )
    op.create_index("ix_ocpc_packages_tenant", "ocpc_packages", ["tenant_id"])

    # 给已存在的内置角色（管理员/运营）补新菜单 edit 权限（品牌方客户不给）
    op.execute(
        """
        UPDATE roles
        SET permissions = permissions || '{"manage.ocpc": "edit"}'::jsonb
        WHERE name IN ('管理员', '运营') AND is_system = true
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = permissions - 'manage.ocpc'
        WHERE name IN ('管理员', '运营') AND is_system = true
        """
    )
    op.drop_index("ix_ocpc_packages_tenant", table_name="ocpc_packages")
    op.drop_table("ocpc_packages")
