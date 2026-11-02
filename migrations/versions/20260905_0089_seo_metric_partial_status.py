"""Allow partial availability for SEO metric snapshots."""

from alembic import op


revision = "0089_seo_metric_partial_status"
down_revision = "0088_seo_image_alt_reviews"
branch_labels = None
depends_on = None


_CONSTRAINT = "ck_seo_metric_snapshot_status"
_TABLE = "seo_metric_snapshots"


def upgrade():
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        _TABLE,
        "status IN ('available','not_configured','pending','partial','failed','stale')",
    )


def downgrade():
    op.execute(
        "UPDATE seo_metric_snapshots SET status = 'failed' WHERE status = 'partial'"
    )
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        _TABLE,
        "status IN ('available','not_configured','pending','failed','stale')",
    )
