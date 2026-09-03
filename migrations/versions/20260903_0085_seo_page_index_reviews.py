"""Human SEO index intent audit trail (main development lineage).

Production has an independent 0084 head: reconcile the migration graph in the
reviewed production promotion PR, never run this migration as a release side effect.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0085_seo_page_index_reviews"
down_revision = "0080_seo_content_review_history"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "seo_page_index_reviews",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("seo_sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_id", sa.BigInteger(), sa.ForeignKey("seo_site_pages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("intent", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_name", sa.String(50), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("intent IN ('undecided', 'index', 'noindex')", name="ck_seo_index_review_intent"),
        sa.CheckConstraint("length(trim(reason)) BETWEEN 1 AND 2000", name="ck_seo_index_review_reason"),
    )
    op.create_index("ix_seo_index_review_scope_page", "seo_page_index_reviews", ["tenant_id", "site_id", "page_id", "id"])
    op.create_index("ix_seo_index_review_page", "seo_page_index_reviews", ["page_id"])
    op.create_index("ix_seo_index_review_site", "seo_page_index_reviews", ["site_id"])


def downgrade():
    op.drop_table("seo_page_index_reviews")
