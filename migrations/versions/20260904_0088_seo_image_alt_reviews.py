"""Human review and Alt suggestion state for stored image evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0088_seo_image_alt_reviews"
down_revision = "0087_seo_image_alt_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "seo_image_alt_reviews",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("seo_sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_id", sa.BigInteger(), sa.ForeignKey("seo_site_pages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_id", sa.BigInteger(), sa.ForeignKey("seo_page_snapshots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("observed_alt_state", sa.String(16), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("alt_suggestion", sa.Text()),
        sa.Column("note", sa.Text()),
        sa.Column("review_status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_name", sa.String(50), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("snapshot_id", "position", name="uq_seo_image_alt_review_snapshot_position"),
        sa.CheckConstraint("position > 0", name="ck_seo_image_alt_review_position"),
        sa.CheckConstraint("observed_alt_state IN ('missing', 'empty', 'whitespace')", name="ck_seo_image_alt_review_observed_state"),
        sa.CheckConstraint("decision IN ('undecided', 'decorative', 'informative')", name="ck_seo_image_alt_review_decision"),
        sa.CheckConstraint("review_status IN ('draft', 'approved')", name="ck_seo_image_alt_review_status"),
        sa.CheckConstraint("alt_suggestion IS NULL OR length(alt_suggestion) <= 300", name="ck_seo_image_alt_review_suggestion"),
    )
    op.create_index("ix_seo_image_alt_review_scope", "seo_image_alt_reviews", ["tenant_id", "site_id", "page_id", "snapshot_id"])


def downgrade():
    op.drop_table("seo_image_alt_reviews")
