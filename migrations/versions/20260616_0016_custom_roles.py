"""custom roles RBAC: roles 表 + users.role(字符串) → role_id(外键)

Revision ID: 0016_custom_roles
Revises: 0015_monthly_reports
Create Date: 2026-06-16

把写死的 admin/operator/client 三角色换成自定义角色：建 roles 表 + seed 3 个内置角色
（管理员/运营/品牌方客户，权限见 app/permissions.py），users.role 字符串回填为 role_id 外键后删除。
tenant_id 保留（限定单客户，独立于角色）。
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.permissions import SYSTEM_ROLES

revision: str = "0016_custom_roles"
down_revision: Union[str, None] = "0015_monthly_reports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 旧角色字符串 → 内置角色名
OLD_TO_NEW = {"admin": "管理员", "operator": "运营", "client": "品牌方客户"}


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("permissions", postgresql.JSONB(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    conn = op.get_bind()
    for r in SYSTEM_ROLES:
        conn.execute(
            sa.text(
                "INSERT INTO roles (name, description, permissions, is_system) "
                "VALUES (:n, :d, cast(:p as jsonb), true)"
            ),
            {"n": r["name"], "d": r["description"], "p": json.dumps(r["permissions"])},
        )

    op.add_column("users", sa.Column("role_id", sa.BigInteger(), nullable=True))
    for old, new in OLD_TO_NEW.items():
        conn.execute(
            sa.text(
                "UPDATE users SET role_id = (SELECT id FROM roles WHERE name = :new) "
                "WHERE role = :old"
            ),
            {"new": new, "old": old},
        )
    # 兜底：任何未匹配到的旧值 → 管理员（避免锁死，理论上不会有）
    conn.execute(
        sa.text(
            "UPDATE users SET role_id = (SELECT id FROM roles WHERE name = '管理员') "
            "WHERE role_id IS NULL"
        )
    )

    op.alter_column("users", "role_id", nullable=False)
    op.create_foreign_key("fk_users_role_id", "users", "roles", ["role_id"], ["id"])
    op.drop_column("users", "role")


def downgrade() -> None:
    op.add_column("users", sa.Column("role", sa.String(10), nullable=True))
    conn = op.get_bind()
    for old, new in OLD_TO_NEW.items():
        conn.execute(
            sa.text(
                "UPDATE users SET role = :old "
                "WHERE role_id = (SELECT id FROM roles WHERE name = :new)"
            ),
            {"old": old, "new": new},
        )
    conn.execute(sa.text("UPDATE users SET role = 'admin' WHERE role IS NULL"))
    op.alter_column("users", "role", nullable=False)
    op.drop_constraint("fk_users_role_id", "users", type_="foreignkey")
    op.drop_column("users", "role_id")
    op.drop_table("roles")
