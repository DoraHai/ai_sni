"""add keyword province summary snapshots.

Revision ID: 0058_kw_region_snapshots
Revises: 0057_seo_rewrite_workflow
Create Date: 2026-08-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0058_kw_region_snapshots"
down_revision: Union[str, None] = "0057_seo_rewrite_workflow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kw_region_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("baidu_account_id", sa.BigInteger(), sa.ForeignKey("baidu_accounts.id")),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("province", sa.String(50), nullable=False),
        sa.Column("cost", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("click", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("impression", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("fetched_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id",
            "report_date",
            "province",
            name="uq_kw_region_snapshot",
        ),
    )


def downgrade() -> None:
    op.drop_table("kw_region_snapshots")
