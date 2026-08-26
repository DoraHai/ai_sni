"""Repair GEO schema skipped before a stamped merge revision.

Revision ID: 0073_geo_schema_repair
Revises: 0072_merge_login_seo
Create Date: 2026-08-19

Some deployed databases were stamped past the GEO 0063/0064 parent
migrations without receiving their DDL. Keep this forward repair idempotent
so it is safe for both affected databases and complete schemas.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0073_geo_schema_repair"
down_revision: Union[str, None] = "0072_merge_login_seo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            ALTER TABLE geo_optimization_businesses
                ADD COLUMN IF NOT EXISTS profile JSONB
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE geo_facts
                ADD COLUMN IF NOT EXISTS business_id BIGINT
                    REFERENCES geo_optimization_businesses(id) ON DELETE SET NULL
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_geo_facts_business_id "
            "ON geo_facts (business_id)"
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS geo_competitor_reports (
                id BIGSERIAL PRIMARY KEY,
                tenant_id BIGINT NOT NULL REFERENCES tenants(id),
                business_id BIGINT REFERENCES geo_optimization_businesses(id) ON DELETE SET NULL,
                period_id BIGINT REFERENCES geo_optimization_periods(id) ON DELETE SET NULL,
                competitor VARCHAR(120) NOT NULL,
                title VARCHAR(240) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'draft',
                insight TEXT,
                action TEXT,
                note TEXT,
                markdown TEXT,
                source_urls JSONB,
                platform_keys JSONB,
                evidence JSONB,
                version_no INTEGER NOT NULL DEFAULT 1,
                created_by BIGINT,
                confirmed_by BIGINT,
                confirmed_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_geo_competitor_reports_tenant_id "
            "ON geo_competitor_reports (tenant_id)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_geo_competitor_reports_competitor "
            "ON geo_competitor_reports (competitor)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_geo_competitor_reports_business_id "
            "ON geo_competitor_reports (business_id)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_geo_competitor_reports_period_id "
            "ON geo_competitor_reports (period_id)"
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS geo_competitor_report_versions (
                id BIGSERIAL PRIMARY KEY,
                report_id BIGINT NOT NULL REFERENCES geo_competitor_reports(id) ON DELETE CASCADE,
                tenant_id BIGINT NOT NULL REFERENCES tenants(id),
                version_no INTEGER NOT NULL,
                markdown TEXT,
                insight TEXT,
                action TEXT,
                note TEXT,
                created_by BIGINT,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_geo_comp_report_ver UNIQUE (report_id, version_no)
            )
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_geo_competitor_report_versions_report_id "
            "ON geo_competitor_report_versions (report_id)"
        )
    )


def downgrade() -> None:
    # These objects belong to historical GEO 0063/0064 migrations. Removing
    # them would make the schema inconsistent with the deployed models.
    pass
