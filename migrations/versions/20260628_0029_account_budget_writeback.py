"""writeback_actions 加 old_value/new_value（通用数值前后快照）+ 内置角色补 manage.account 权限

Revision ID: 0029_account_budget_writeback
Revises: 0028_ocpc_packages
Create Date: 2026-06-28

账户日预算写回（投放管理第一步，安全总闸 / L1 引导第一步）：updateAccountInfo budget。
账户级操作无 keyword/campaign，台账（writeback_actions）复用，加通用 old_value/new_value 记
预算前后值（将来计划日预算写回也用这两列）。新菜单 manage.account（投放管理组）给内置角色
（管理员/运营）补 edit，否则进不去。写回受 dry-run + 合法区间 + 台账保护（演练只记台账不真改）。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029_account_budget_writeback"
down_revision: Union[str, None] = "0028_ocpc_packages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("writeback_actions", sa.Column("old_value", sa.Numeric(12, 2)))
    op.add_column("writeback_actions", sa.Column("new_value", sa.Numeric(12, 2)))

    op.execute(
        """
        UPDATE roles
        SET permissions = permissions || '{"manage.account": "edit"}'::jsonb
        WHERE name IN ('管理员', '运营') AND is_system = true
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = permissions - 'manage.account'
        WHERE name IN ('管理员', '运营') AND is_system = true
        """
    )
    op.drop_column("writeback_actions", "new_value")
    op.drop_column("writeback_actions", "old_value")
