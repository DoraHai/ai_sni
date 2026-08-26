"""add alert entity_ref for non-keyword alerts.

Revision ID: 0059_alert_entity_ref
Revises: 0058_kw_region_snapshots
Create Date: 2026-08-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0059_alert_entity_ref"
down_revision: Union[str, None] = "0058_kw_region_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("entity_ref", sa.String(length=100), nullable=True))
    op.drop_constraint("uq_alerts_tenant_rule_kw_date", "alerts", type_="unique")
    op.create_unique_constraint(
        "uq_alerts_tenant_rule_kw_entity_date",
        "alerts",
        ["tenant_id", "rule_code", "keyword_id", "entity_ref", "report_date"],
    )
    op.create_index(
        "ux_alerts_keyword_dedup",
        "alerts",
        ["tenant_id", "rule_code", "keyword_id", "report_date"],
        unique=True,
        postgresql_where=sa.text("keyword_id IS NOT NULL"),
    )
    op.create_index(
        "ux_alerts_entity_dedup",
        "alerts",
        ["tenant_id", "rule_code", "entity_ref", "report_date"],
        unique=True,
        postgresql_where=sa.text("entity_ref IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_alerts_entity_dedup", table_name="alerts")
    op.drop_index("ux_alerts_keyword_dedup", table_name="alerts")
    op.drop_constraint("uq_alerts_tenant_rule_kw_entity_date", "alerts", type_="unique")
    op.create_unique_constraint(
        "uq_alerts_tenant_rule_kw_date",
        "alerts",
        ["tenant_id", "rule_code", "keyword_id", "report_date"],
    )
    op.drop_column("alerts", "entity_ref")
