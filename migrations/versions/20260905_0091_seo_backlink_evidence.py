"""Store SEO backlink observations without altering historical link status."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0091_seo_backlink_evidence"
down_revision = "0090_seo_ai_operations"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("seo_backlinks", sa.Column("verification", postgresql.JSONB(), nullable=True))
    op.add_column("seo_content_publications", sa.Column("link_discovery", postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column("seo_content_publications", "link_discovery")
    op.drop_column("seo_backlinks", "verification")
