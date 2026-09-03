"""Optional image evidence; historical snapshots remain unknown, not empty.

Prepare only. Requires separate reviewed schema authorization before deployment.
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0087_seo_image_alt_evidence"
down_revision = "0085_seo_page_index_reviews"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("seo_page_snapshots", sa.Column("image_alt_evidence", postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column("seo_page_snapshots", "image_alt_evidence")
