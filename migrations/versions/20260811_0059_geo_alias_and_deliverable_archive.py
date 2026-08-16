"""competitor aliases + deliverable pack archives

Revision ID: 0059_geo_alias_deliverable
Revises: 0058_geo_snapshot_patrol_sample
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0059_geo_alias_deliverable"
down_revision: Union[str, None] = "0058_geo_snapshot_patrol_sample"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geo_competitor_aliases",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("alias_name", sa.String(200), nullable=False),
        sa.Column("canonical_name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "alias_name", name="uq_geo_comp_alias_tenant_alias"),
    )
    op.create_index("ix_geo_competitor_aliases_tenant_id", "geo_competitor_aliases", ["tenant_id"])

    op.create_table(
        "geo_deliverable_archives",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("period_from", sa.DateTime(), nullable=True),
        sa.Column("period_to", sa.DateTime(), nullable=True),
        sa.Column("pack_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=True),
        sa.Column("share_token", sa.String(64), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.UniqueConstraint("share_token", name="uq_geo_deliverable_share_token"),
    )
    op.create_index(
        "ix_geo_deliverable_archives_tenant_id", "geo_deliverable_archives", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_table("geo_deliverable_archives")
    op.drop_table("geo_competitor_aliases")
