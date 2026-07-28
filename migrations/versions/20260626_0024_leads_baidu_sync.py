"""leads 加百度同步字段：external_id(clueId 去重) + keyword(词级归因) + connect(接通)

Revision ID: 0024_leads_baidu_sync
Revises: 0023_leads
Create Date: 2026-06-26

文档 0819 LeadsNoticeService/getNoticeList 能直接拉基木鱼线索明细，苏尔寿实测电话组件有
真线索且 100% 可归因到关键词。本迁移给 leads 加：external_id(百度 clueId，幂等去重，手动录入
为 NULL) + keyword(触发关键词名，词级归因) + connect(电话接通状态 1/0)。partial unique 保证
同一 clueId 不重复落库（手动录入 external_id=NULL 不受唯一约束影响，PG 多 NULL 不冲突）。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024_leads_baidu_sync"
down_revision: Union[str, None] = "0023_leads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("external_id", sa.String(64)))
    op.add_column("leads", sa.Column("keyword", sa.Text()))
    op.add_column("leads", sa.Column("connect", sa.SmallInteger()))
    # 幂等去重：同租户内同一 clueId 只落一条；手动录入 external_id=NULL 不进唯一约束
    op.create_index(
        "uq_leads_tenant_external",
        "leads",
        ["tenant_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_leads_tenant_external", table_name="leads")
    op.drop_column("leads", "connect")
    op.drop_column("leads", "keyword")
    op.drop_column("leads", "external_id")
