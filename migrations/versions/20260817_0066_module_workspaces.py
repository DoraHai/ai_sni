"""Add module subscriptions and per-module business subjects.

Revision ID: 0066_module_workspaces
Revises: 0065_seo_rewrite_schema_repair
Create Date: 2026-08-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0066_module_workspaces"
down_revision: Union[str, None] = "0065_seo_rewrite_schema_repair"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenant_modules",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("module_code", sa.String(16), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("opened_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.Date(), nullable=True),
        sa.Column("module_settings", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "module_code", name="uq_tenant_module_code"),
        sa.CheckConstraint("module_code IN ('sem','seo','geo')", name="ck_tenant_module_code"),
        sa.CheckConstraint("status IN ('active','trial','suspended','closed')", name="ck_tenant_module_status"),
    )
    op.create_index("ix_tenant_modules_tenant_id", "tenant_modules", ["tenant_id"])
    op.create_index("ix_tenant_modules_module_code", "tenant_modules", ["module_code"])
    op.create_index("ix_tenant_modules_status", "tenant_modules", ["status"])

    op.create_table(
        "seo_sites",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_module_id", sa.BigInteger(), sa.ForeignKey("tenant_modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("canonical_domain", sa.String(255), nullable=False),
        sa.Column("default_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("site_settings", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "canonical_domain", name="uq_seo_site_tenant_domain"),
    )
    op.create_index("ix_seo_sites_tenant_id", "seo_sites", ["tenant_id"])
    op.create_index("ix_seo_sites_tenant_module_id", "seo_sites", ["tenant_module_id"])
    op.create_index("ix_seo_sites_canonical_domain", "seo_sites", ["canonical_domain"])
    op.create_index("ix_seo_sites_status", "seo_sites", ["status"])

    op.create_table(
        "geo_projects",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_module_id", sa.BigInteger(), sa.ForeignKey("tenant_modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("brand_name", sa.String(160), nullable=True),
        sa.Column("primary_domain", sa.String(255), nullable=False),
        sa.Column("canonical_domain", sa.String(255), nullable=False),
        sa.Column("default_url", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("project_settings", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "canonical_domain", name="uq_geo_project_tenant_domain"),
    )
    op.create_index("ix_geo_projects_tenant_id", "geo_projects", ["tenant_id"])
    op.create_index("ix_geo_projects_tenant_module_id", "geo_projects", ["tenant_module_id"])
    op.create_index("ix_geo_projects_canonical_domain", "geo_projects", ["canonical_domain"])
    op.create_index("ix_geo_projects_status", "geo_projects", ["status"])

    # Existing installations were SEM-first, so retain every current customer in SEM.
    op.execute(sa.text("""
        INSERT INTO tenant_modules (tenant_id, module_code, status)
        SELECT id, 'sem', 'active' FROM tenants
        ON CONFLICT (tenant_id, module_code) DO NOTHING
    """))

    # Existing system roles receive module-subject management. Only platform
    # administrators (already holding settings.accounts=edit) receive customer master access.
    op.execute(sa.text("""
        UPDATE roles
        SET permissions = COALESCE(permissions, '{}'::jsonb) ||
            '{"sem.assets":"edit","seo.assets":"edit","geo.assets":"edit"}'::jsonb
        WHERE is_system = TRUE
    """))
    op.execute(sa.text("""
        UPDATE roles
        SET permissions = COALESCE(permissions, '{}'::jsonb) ||
            '{"settings.customers":"edit"}'::jsonb
        WHERE permissions ->> 'settings.accounts' = 'edit'
    """))
    # Only opt customers into SEO/GEO when corresponding data already exists.
    op.execute(sa.text("""
        INSERT INTO tenant_modules (tenant_id, module_code, status)
        SELECT DISTINCT tenant_id, 'seo', 'active' FROM seo_keyword_assets
        ON CONFLICT (tenant_id, module_code) DO NOTHING
    """))
    op.execute(sa.text("""
        INSERT INTO tenant_modules (tenant_id, module_code, status)
        SELECT DISTINCT tenant_id, 'geo', 'active' FROM geo_audit_runs
        ON CONFLICT (tenant_id, module_code) DO NOTHING
    """))
    op.execute(sa.text("""
        INSERT INTO tenant_modules (tenant_id, module_code, status)
        SELECT DISTINCT tenant_id, 'geo', 'active' FROM geo_optimization_businesses
        ON CONFLICT (tenant_id, module_code) DO NOTHING
    """))


def downgrade() -> None:
    op.execute(sa.text("""
        UPDATE roles
        SET permissions = COALESCE(permissions, '{}'::jsonb)
            - 'sem.assets' - 'seo.assets' - 'geo.assets' - 'settings.customers'
    """))
    op.drop_table("geo_projects")
    op.drop_table("seo_sites")
    op.drop_table("tenant_modules")
