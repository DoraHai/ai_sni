"""Clean known corrupted local GEO demo labels.

Revision ID: 0048_clean_legacy_geo_demo_text
Revises: 0047_geo_review_channels
"""

from alembic import op
import sqlalchemy as sa

from app.geo.content.legacy_demo_cleanup import clean_legacy_demo_fact, clean_legacy_demo_task


revision = "0048_clean_legacy_geo_demo_text"
down_revision = "0047_geo_review_channels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    task_rows = bind.execute(
        sa.text("SELECT id, title FROM geo_content_tasks WHERE title = :title"),
        {"title": "[???] ????????"},
    ).mappings()
    for row in task_rows:
        cleaned = clean_legacy_demo_task(row["title"], row["id"])
        bind.execute(
            sa.text("UPDATE geo_content_tasks SET title = :title WHERE id = :id"),
            {"title": cleaned, "id": row["id"]},
        )

    fact_rows = bind.execute(
        sa.text("SELECT id, title, source_name FROM geo_facts WHERE title LIKE '????%'"),
    ).mappings()
    for row in fact_rows:
        cleaned = clean_legacy_demo_fact(row["title"], row["source_name"])
        if cleaned != row["title"]:
            bind.execute(
                sa.text("UPDATE geo_facts SET title = :title WHERE id = :id"),
                {"title": cleaned, "id": row["id"]},
            )


def downgrade() -> None:
    # The old labels were corrupted and cannot be reconstructed safely.
    pass
