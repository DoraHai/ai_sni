"""Merge the deployed login-lockout and SEO distribution migration heads.

Revision ID: 0072_merge_login_seo
Revises: 0071_login_lockout, 0071_seo_distribution
Create Date: 2026-08-19
"""

from typing import Sequence, Union


revision: str = "0072_merge_login_seo"
down_revision: Union[str, tuple[str, str]] = (
    "0071_login_lockout",
    "0071_seo_distribution",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
