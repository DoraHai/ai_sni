"""add temporary account lockout state

Revision ID: 0071_login_lockout
Revises: 0070_seo_content_keywords
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0071_login_lockout"
down_revision: Union[str, None] = "0070_seo_content_keywords"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "failed_login_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column("users", sa.Column("last_failed_login_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("locked_until", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "locked_until")
    op.drop_column("users", "last_failed_login_at")
    op.drop_column("users", "failed_login_attempts")
