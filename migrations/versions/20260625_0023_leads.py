"""leads 客户真线索台账（手动录入起步）+ 给内置角色补 verify.leads 菜单权限

Revision ID: 0023_leads
Revises: 0022_candidate_ai_bid
Create Date: 2026-06-25

百度埋码转化是代理指标，真线索质量/成交在客户销售台账里。本表让客户把真线索录进来，
和消费对齐算真实线索成本，是产品三层 L1 小白模式地基。新菜单 verify.leads 需给已存在的
内置角色（管理员/运营）补 edit 权限，否则连管理员都进不去（角色权限存在 DB，0016 种的）。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023_leads"
down_revision: Union[str, None] = "0022_candidate_ai_bid"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("contact_name", sa.String(100)),
        sa.Column("phone", sa.String(50)),
        sa.Column("source_channel", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("campaign_id", sa.BigInteger()),
        sa.Column("campaign_name", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False, server_default="new"),
        sa.Column("intent_level", sa.String(10)),
        sa.Column("deal_amount", sa.Numeric(12, 2)),
        sa.Column("lead_time", sa.Date()),
        sa.Column("note", sa.Text()),
        sa.Column("operator_user_id", sa.BigInteger()),
        sa.Column("operator_name", sa.String(100)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("ix_leads_tenant", "leads", ["tenant_id"])
    op.create_index("ix_leads_status", "leads", ["tenant_id", "status"])

    # 给已存在的内置角色（管理员/运营）补新菜单 edit 权限（品牌方客户不给）
    op.execute(
        """
        UPDATE roles
        SET permissions = permissions || '{"verify.leads": "edit"}'::jsonb
        WHERE name IN ('管理员', '运营') AND is_system = true
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = permissions - 'verify.leads'
        WHERE name IN ('管理员', '运营') AND is_system = true
        """
    )
    op.drop_index("ix_leads_status", table_name="leads")
    op.drop_index("ix_leads_tenant", table_name="leads")
    op.drop_table("leads")
