"""Track SEM asset sync status by dimension.

Revision ID: 0075_sem_asset_sync_state
Revises: 0074_suggestion_workflow
Create Date: 2026-08-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0075_sem_asset_sync_state"
down_revision: Union[str, None] = "0074_suggestion_workflow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "baidu_accounts",
        sa.Column("asset_sync_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("baidu_accounts", "asset_sync_state")
