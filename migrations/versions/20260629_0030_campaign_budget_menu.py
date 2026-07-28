"""内置角色补 manage.campaigns 菜单权限（计划管理页：计划日预算写回）

Revision ID: 0030_campaign_budget_menu
Revises: 0029_account_budget_writeback
Create Date: 2026-06-29

计划日预算写回（updateCampaign budget）复用 writeback_actions 台账（0029 已加 old_value/
new_value 通用列，action_type=set_campaign_budget），无新增表。仅新菜单 manage.campaigns
需给内置角色（管理员/运营）补 edit，否则进不去。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0030_campaign_budget_menu"
down_revision: Union[str, None] = "0029_account_budget_writeback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = permissions || '{"manage.campaigns": "edit"}'::jsonb
        WHERE name IN ('管理员', '运营') AND is_system = true
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = permissions - 'manage.campaigns'
        WHERE name IN ('管理员', '运营') AND is_system = true
        """
    )
