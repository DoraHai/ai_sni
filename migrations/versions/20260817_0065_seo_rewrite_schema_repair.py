"""Repair schema skipped when merge heads were stamped.

Revision ID: 0065_seo_rewrite_schema_repair
Revises: 0064_merge_geo_sem_heads
Create Date: 2026-08-17

Some deployed databases were stamped at ``0064_merge_geo_sem_heads`` without
receiving parent alterations (SEO 0057, GEO 0063/0064). Keep this repair
idempotent so it is safe for both affected databases and complete schemas.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0065_seo_rewrite_schema_repair"
down_revision: Union[str, None] = "0064_merge_geo_sem_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            ALTER TABLE seo_content_assets
                ADD COLUMN IF NOT EXISTS source_text TEXT,
                ADD COLUMN IF NOT EXISTS rewrite_progress SMALLINT,
                ADD COLUMN IF NOT EXISTS originality_score SMALLINT,
                ADD COLUMN IF NOT EXISTS target_platforms JSONB,
                ADD COLUMN IF NOT EXISTS version_count INTEGER NOT NULL DEFAULT 1
            """
        )
    )

    # GEO 0063/0064 were skipped on some stamped-merge databases.
    # Missing geo_facts.business_id makes POST /content-tasks return 500:
    # create always SELECTs facts (even with zero bindings).
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
            "CREATE INDEX IF NOT EXISTS ix_geo_facts_business_id ON geo_facts (business_id)"
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
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_geo_competitor_reports_tenant_id ON geo_competitor_reports (tenant_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_geo_competitor_reports_competitor ON geo_competitor_reports (competitor)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_geo_competitor_reports_business_id ON geo_competitor_reports (business_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_geo_competitor_reports_period_id ON geo_competitor_reports (period_id)"))
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
            "CREATE INDEX IF NOT EXISTS ix_geo_competitor_report_versions_report_id ON geo_competitor_report_versions (report_id)"
        )
    )


def downgrade() -> None:
    # Historical columns/tables belong to 0057/0063/0064. Removing them on
    # downgrade would make the schema inconsistent with the merge-head models.
    pass
