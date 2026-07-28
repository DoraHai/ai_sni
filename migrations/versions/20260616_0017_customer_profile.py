"""customer profile: tenants 画像字段 + 角色补 monitor.profile 菜单权限

Revision ID: 0017_customer_profile
Revises: 0016_custom_roles
Create Date: 2026-06-16

客户画像：tenants 加 industry/business_desc(可编辑)/profile_summary/profile_generated_at(AI 总结缓存)。
新增 monitor.profile 菜单 → 给已 seed 的内置角色补权限（管理员/运营 edit、品牌方客户 view），
否则迁移 0016 之后的角色没有这个新菜单权限。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_customer_profile"
down_revision: Union[str, None] = "0016_custom_roles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("industry", sa.String(100), nullable=True))
    op.add_column("tenants", sa.Column("business_desc", sa.Text(), nullable=True))
    op.add_column("tenants", sa.Column("profile_summary", sa.Text(), nullable=True))
    op.add_column("tenants", sa.Column("profile_generated_at", sa.DateTime(), nullable=True))

    conn = op.get_bind()
    # 苏尔寿默认行业（之前写死在 prompt 里的）
    conn.execute(
        sa.text("UPDATE tenants SET industry = '工业泵 / 分离技术' WHERE name LIKE '苏尔寿%'")
    )
    # 给内置角色补 monitor.profile（jsonb 合并；已有则不覆盖原有键）
    conn.execute(sa.text(
        "UPDATE roles SET permissions = permissions || '{\"monitor.profile\":\"edit\"}'::jsonb "
        "WHERE name IN ('管理员', '运营')"
    ))
    conn.execute(sa.text(
        "UPDATE roles SET permissions = permissions || '{\"monitor.profile\":\"view\"}'::jsonb "
        "WHERE name = '品牌方客户'"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE roles SET permissions = permissions - 'monitor.profile'"))
    op.drop_column("tenants", "profile_generated_at")
    op.drop_column("tenants", "profile_summary")
    op.drop_column("tenants", "business_desc")
    op.drop_column("tenants", "industry")
