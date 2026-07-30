"""GEO content workbench tables and geo.content permission

Revision ID: 0036_geo_content_workbench
Revises: 0035_geo_audits
Create Date: 2026-07-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036_geo_content_workbench"
down_revision: Union[str, None] = "0035_geo_audits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "geo_prompts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False, server_default="zh-CN"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tags", postgresql.JSONB(), nullable=True),
        sa.Column("demand_note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_geo_prompts_tenant_id", "geo_prompts", ["tenant_id"])

    op.create_table(
        "geo_facts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("fact_type", sa.String(length=32), nullable=False, server_default="product"),
        sa.Column("source_name", sa.String(length=200), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.Date(), nullable=True),
        sa.Column("trust_level", sa.String(length=16), nullable=False, server_default="needs_review"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("meta", postgresql.JSONB(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_geo_facts_tenant_id", "geo_facts", ["tenant_id"])

    op.create_table(
        "geo_content_tasks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("prompt_id", sa.BigInteger(), sa.ForeignKey("geo_prompts.id"), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("target_channels", postgresql.JSONB(), nullable=True),
        sa.Column("owner_user_id", sa.BigInteger(), nullable=True),
        sa.Column("brief", postgresql.JSONB(), nullable=True),
        sa.Column("rule_result", postgresql.JSONB(), nullable=True),
        sa.Column("ready_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_geo_content_tasks_tenant_id", "geo_content_tasks", ["tenant_id"])
    op.create_index("ix_geo_content_tasks_prompt_id", "geo_content_tasks", ["prompt_id"])
    op.create_index(
        "ix_geo_content_tasks_tenant_status", "geo_content_tasks", ["tenant_id", "status"]
    )

    op.create_table(
        "geo_task_facts",
        sa.Column(
            "task_id",
            sa.BigInteger(),
            sa.ForeignKey("geo_content_tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "fact_id",
            sa.BigInteger(),
            sa.ForeignKey("geo_facts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "geo_article_versions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "task_id",
            sa.BigInteger(),
            sa.ForeignKey("geo_content_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="master"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("outline", postgresql.JSONB(), nullable=True),
        sa.Column("generation_meta", postgresql.JSONB(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_geo_article_versions_task_id", "geo_article_versions", ["task_id"])

    op.create_table(
        "geo_channel_variants",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "task_id",
            sa.BigInteger(),
            sa.ForeignKey("geo_content_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "article_version_id",
            sa.BigInteger(),
            sa.ForeignKey("geo_article_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column("export_format", sa.String(length=16), nullable=False, server_default="markdown"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_geo_channel_variants_task_id", "geo_channel_variants", ["task_id"])

    op.create_table(
        "geo_publications",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "variant_id",
            sa.BigInteger(),
            sa.ForeignKey("geo_channel_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("publish_mode", sa.String(length=20), nullable=False, server_default="manual_export"),
        sa.Column("published_url", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_geo_publications_variant_id", "geo_publications", ["variant_id"])

    # PostgreSQL sequences for BigInteger PKs (match other GEO/SEM tables that rely on serial-like ids)
    for table in (
        "geo_prompts",
        "geo_facts",
        "geo_content_tasks",
        "geo_article_versions",
        "geo_channel_variants",
        "geo_publications",
    ):
        op.execute(sa.text(f"CREATE SEQUENCE IF NOT EXISTS {table}_id_seq"))
        op.execute(
            sa.text(
                f"ALTER TABLE {table} ALTER COLUMN id SET DEFAULT nextval('{table}_id_seq')"
            )
        )
        op.execute(sa.text(f"ALTER SEQUENCE {table}_id_seq OWNED BY {table}.id"))

    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE roles SET permissions = permissions || "
            "'{\"geo.content\":\"edit\"}'::jsonb "
            "WHERE name IN ('管理员', '运营')"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE roles SET permissions = permissions || "
            "'{\"geo.content\":\"view\"}'::jsonb "
            "WHERE name = '品牌方客户'"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE roles SET permissions = permissions - 'geo.content'"))
    op.drop_index("ix_geo_publications_variant_id", table_name="geo_publications")
    op.drop_table("geo_publications")
    op.drop_index("ix_geo_channel_variants_task_id", table_name="geo_channel_variants")
    op.drop_table("geo_channel_variants")
    op.drop_index("ix_geo_article_versions_task_id", table_name="geo_article_versions")
    op.drop_table("geo_article_versions")
    op.drop_table("geo_task_facts")
    op.drop_index("ix_geo_content_tasks_tenant_status", table_name="geo_content_tasks")
    op.drop_index("ix_geo_content_tasks_prompt_id", table_name="geo_content_tasks")
    op.drop_index("ix_geo_content_tasks_tenant_id", table_name="geo_content_tasks")
    op.drop_table("geo_content_tasks")
    op.drop_index("ix_geo_facts_tenant_id", table_name="geo_facts")
    op.drop_table("geo_facts")
    op.drop_index("ix_geo_prompts_tenant_id", table_name="geo_prompts")
    op.drop_table("geo_prompts")
