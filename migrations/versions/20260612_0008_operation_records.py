"""add operation_records (百度操作记录/调价台账)

Revision ID: 0008_operation_records
Revises: 0007_price_ratio
Create Date: 2026-06-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_operation_records"
down_revision: Union[str, None] = "0007_price_ratio"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "operation_records",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "baidu_account_id", sa.BigInteger(), sa.ForeignKey("baidu_accounts.id"), nullable=True
        ),
        sa.Column("opt_time", sa.DateTime(), nullable=False),
        sa.Column("opt_type", sa.SmallInteger(), nullable=True),
        sa.Column("opt_level", sa.SmallInteger(), nullable=True),
        sa.Column("opt_content", sa.String(50), nullable=True),
        sa.Column("opt_obj", sa.Text(), nullable=True),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("plan_id", sa.BigInteger(), nullable=True),
        sa.Column("unit_id", sa.BigInteger(), nullable=True),
        sa.Column("dedup_key", sa.String(32), nullable=False),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "dedup_key", name="uq_operation_records_tenant_dedup"),
    )
    op.create_index(
        "ix_operation_records_tenant_time",
        "operation_records",
        ["tenant_id", "opt_time"],
    )


def downgrade() -> None:
    op.drop_index("ix_operation_records_tenant_time", table_name="operation_records")
    op.drop_table("operation_records")
