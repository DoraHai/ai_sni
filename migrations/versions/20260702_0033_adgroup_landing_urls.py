"""adgroups 增加单元最终访问网址字段

Revision ID: 0033_adgroup_landing_urls
Revises: 0032_assistant_user_scope
Create Date: 2026-07-02

单元管理页展示并编辑 AdgroupService 的 URL 拆分字段：
pcFinalUrl / mobileFinalUrl 以及监控后缀、第三方追踪模板。
写回仍受 BAIDU_WRITE_DRY_RUN 演练开关保护。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0033_adgroup_landing_urls"
down_revision: Union[str, None] = "0032_assistant_user_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("adgroups", sa.Column("pc_final_url", sa.Text()))
    op.add_column("adgroups", sa.Column("mobile_final_url", sa.Text()))
    op.add_column("adgroups", sa.Column("pc_track_param", sa.Text()))
    op.add_column("adgroups", sa.Column("mobile_track_param", sa.Text()))
    op.add_column("adgroups", sa.Column("pc_track_template", sa.Text()))
    op.add_column("adgroups", sa.Column("mobile_track_template", sa.Text()))


def downgrade() -> None:
    op.drop_column("adgroups", "mobile_track_template")
    op.drop_column("adgroups", "pc_track_template")
    op.drop_column("adgroups", "mobile_track_param")
    op.drop_column("adgroups", "pc_track_param")
    op.drop_column("adgroups", "mobile_final_url")
    op.drop_column("adgroups", "pc_final_url")
