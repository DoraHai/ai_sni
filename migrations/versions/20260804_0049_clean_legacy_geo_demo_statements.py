"""Clean known corrupted local GEO demo fact statements.

Revision ID: 0049_geo_demo_statement_cleanup
Revises: 0048_clean_legacy_geo_demo_text
"""

from alembic import op
import sqlalchemy as sa

from app.geo.content.legacy_demo_cleanup import clean_legacy_demo_fact_statement


revision = "0049_geo_demo_statement_cleanup"
down_revision = "0048_clean_legacy_geo_demo_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, statement, source_name FROM geo_facts "
            "WHERE source_name LIKE 'demo-source-%' OR source_name LIKE 'seed-%'"
        )
    ).mappings()
    for row in rows:
        cleaned = clean_legacy_demo_fact_statement(row["statement"], row["source_name"])
        if cleaned != row["statement"]:
            bind.execute(
                sa.text("UPDATE geo_facts SET statement = :statement WHERE id = :id"),
                {"statement": cleaned, "id": row["id"]},
            )


def downgrade() -> None:
    # The original statements were corrupted and cannot be reconstructed safely.
    pass
