"""Merge the GEO and platform migration branches.

Revision ID: 0055_merge_geo_platform
Revises: 0038_oauth_account_tenants, 0054_geo_opt_hierarchy
"""

from typing import Sequence, Union


revision: str = "0055_merge_geo_platform"
down_revision: Union[str, tuple[str, str], None] = (
    "0038_oauth_account_tenants",
    "0054_geo_opt_hierarchy",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Join both histories; schema changes are owned by the parent revisions."""


def downgrade() -> None:
    """Split back to the two parent heads without changing schema objects."""
