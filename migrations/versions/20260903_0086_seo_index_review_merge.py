"""Join the immutable main index-review migration and SEO production history.

From production 0084: create the review table via 0085, then merge the heads.
No schema changes in this merge node; earlier migrations are preserved verbatim.
"""

revision = "0086_seo_index_review_merge"
down_revision = ("0084_seo_crawl_queued_status", "0085_seo_page_index_reviews")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
