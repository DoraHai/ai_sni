"""DRAFT ONLY: not in script_location; do not copy/run before lineage approval.

Candidate contract for SEO compatibility review, not production authorization.
Parent exists on the reviewed SEO lineage, not yet on main. Preserve all
historical revisions. The final migration package requires a separate review.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0095_sem_tasks"
down_revision = "0094_seo_qa_batches"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sem_tasks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(),
                  sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("module", sa.String(8), nullable=False),
        sa.Column("action_type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("params", JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_by", sa.String(80), nullable=False),
        sa.Column("assignee_role", sa.String(64), nullable=False),
        sa.Column("baseline_snapshot", JSONB(), nullable=False),
        sa.Column("completion_evidence", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("module = 'sem'", name="ck_sem_tasks_module"),
        sa.CheckConstraint("action_type = 'metric_target'", name="ck_sem_tasks_action"),
        sa.CheckConstraint("status IN ('open','in_progress','done','cancelled')", name="ck_sem_tasks_status"),
        sa.CheckConstraint("assignee_role IN ('operator','admin')", name="ck_sem_tasks_role"),
        sa.CheckConstraint("jsonb_typeof(params) = 'object'", name="ck_sem_tasks_params"),
        sa.CheckConstraint("jsonb_typeof(baseline_snapshot) = 'object'", name="ck_sem_tasks_baseline"),
        sa.CheckConstraint("completion_evidence IS NULL OR jsonb_typeof(completion_evidence) = 'object'", name="ck_sem_tasks_evidence"),
        sa.CheckConstraint("(status = 'done' AND completion_evidence IS NOT NULL) OR (status <> 'done' AND completion_evidence IS NULL)", name="ck_sem_tasks_done"),
    )
    op.create_index("ix_sem_tasks_action", "sem_tasks", ["tenant_id", "action_type", "id"])
    op.create_index("ix_sem_tasks_queue", "sem_tasks", ["tenant_id", "status", "id"])


def downgrade():
    raise RuntimeError("Destructive rollback is not authorized: retain SemTask audit data and disable the feature.")
