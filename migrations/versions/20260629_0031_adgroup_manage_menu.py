"""内置角色补 manage.adgroups 菜单权限（单元管理：单元启停 + 单元出价写回）

Revision ID: 0031_adgroup_manage_menu
Revises: 0030_campaign_budget_menu
Create Date: 2026-06-29

计划启停 / 单元启停 / 单元出价写回复用 writeback_actions 台账（action_type=
campaign_pause/campaign_enable/adgroup_pause/adgroup_enable/set_adgroup_bid），无新增表。
计划启停挂在已有「计划管理」页；新增「单元管理」页 manage.adgroups 需给内置角色补 edit。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0031_adgroup_manage_menu"
down_revision: Union[str, None] = "0030_campaign_budget_menu"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = permissions || '{"manage.adgroups": "edit"}'::jsonb
        WHERE name IN ('管理员', '运营') AND is_system = true
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = permissions - 'manage.adgroups'
        WHERE name IN ('管理员', '运营') AND is_system = true
        """
    )
