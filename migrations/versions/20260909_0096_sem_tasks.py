"""Create the reviewed SEM task audit table.

The table starts empty and does not enable the SEM task API or any advertising
write path.  The migration is intentionally irreversible because baseline and
completion evidence must survive an application rollback.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0096_sem_tasks"
down_revision = "0095_adopt_geo_ticket"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sem_tasks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("module", sa.String(length=8), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("params", JSONB(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by", sa.String(length=80), nullable=False),
        sa.Column("assignee_role", sa.String(length=64), nullable=False),
        sa.Column("baseline_snapshot", JSONB(), nullable=False),
        sa.Column("completion_evidence", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("module = 'sem'", name="ck_sem_tasks_module"),
        sa.CheckConstraint(
            "action_type = 'metric_target'", name="ck_sem_tasks_action"
        ),
        sa.CheckConstraint(
            "status IN ('open','in_progress','done','cancelled')",
            name="ck_sem_tasks_status",
        ),
        sa.CheckConstraint(
            "assignee_role IN ('operator','admin')", name="ck_sem_tasks_role"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(params) = 'object'", name="ck_sem_tasks_params"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(baseline_snapshot) = 'object'",
            name="ck_sem_tasks_baseline",
        ),
        sa.CheckConstraint(
            "completion_evidence IS NULL "
            "OR jsonb_typeof(completion_evidence) = 'object'",
            name="ck_sem_tasks_evidence",
        ),
        sa.CheckConstraint(
            "(status = 'done' AND completion_evidence IS NOT NULL) "
            "OR (status <> 'done' AND completion_evidence IS NULL)",
            name="ck_sem_tasks_done",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_sem_tasks_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_sem_tasks_action",
        "sem_tasks",
        ["tenant_id", "action_type", "id"],
    )
    op.create_index(
        "ix_sem_tasks_queue",
        "sem_tasks",
        ["tenant_id", "status", "id"],
    )
    op.create_index(
        "ix_sem_tasks_tenant_id_id",
        "sem_tasks",
        ["tenant_id", "id"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "0096_sem_tasks is irreversible: retain task evidence and disable the feature"
    )
