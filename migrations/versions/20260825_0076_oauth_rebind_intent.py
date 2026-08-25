"""persist OAuth rebind intent and funds writeback approval links

Revision ID: 0076_oauth_rebind_intent
Revises: 0075_sem_asset_sync_state
"""

from alembic import op
import sqlalchemy as sa


revision = "0076_oauth_rebind_intent"
down_revision = "0075_sem_asset_sync_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "baidu_oauth_states",
        sa.Column(
            "bind_to_tenant",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("bid_writebacks", sa.Column("approval_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_bid_writebacks_approval_id",
        "bid_writebacks", "writeback_approvals", ["approval_id"], ["id"],
    )
    op.create_index("ix_bid_writebacks_approval_id", "bid_writebacks", ["approval_id"])
    op.add_column("bid_writebacks", sa.Column("reconciliation_result", sa.String(32)))
    op.add_column("bid_writebacks", sa.Column("reconciliation_note", sa.Text()))
    op.add_column("bid_writebacks", sa.Column("reconciled_by", sa.BigInteger()))
    op.add_column("bid_writebacks", sa.Column("reconciled_at", sa.DateTime()))
    op.create_foreign_key(
        "fk_bid_writebacks_reconciled_by",
        "bid_writebacks", "users", ["reconciled_by"], ["id"],
    )
    op.add_column("writeback_actions", sa.Column("approval_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_writeback_actions_approval_id",
        "writeback_actions", "writeback_approvals", ["approval_id"], ["id"],
    )
    op.create_index("ix_writeback_actions_approval_id", "writeback_actions", ["approval_id"])
    op.add_column("writeback_actions", sa.Column("reconciliation_result", sa.String(32)))
    op.add_column("writeback_actions", sa.Column("reconciliation_note", sa.Text()))
    op.add_column("writeback_actions", sa.Column("reconciled_by", sa.BigInteger()))
    op.add_column("writeback_actions", sa.Column("reconciled_at", sa.DateTime()))
    op.create_foreign_key(
        "fk_writeback_actions_reconciled_by",
        "writeback_actions", "users", ["reconciled_by"], ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_writeback_actions_reconciled_by", "writeback_actions", type_="foreignkey")
    op.drop_column("writeback_actions", "reconciled_at")
    op.drop_column("writeback_actions", "reconciled_by")
    op.drop_column("writeback_actions", "reconciliation_note")
    op.drop_column("writeback_actions", "reconciliation_result")
    op.drop_index("ix_writeback_actions_approval_id", table_name="writeback_actions")
    op.drop_constraint("fk_writeback_actions_approval_id", "writeback_actions", type_="foreignkey")
    op.drop_column("writeback_actions", "approval_id")
    op.drop_constraint("fk_bid_writebacks_reconciled_by", "bid_writebacks", type_="foreignkey")
    op.drop_column("bid_writebacks", "reconciled_at")
    op.drop_column("bid_writebacks", "reconciled_by")
    op.drop_column("bid_writebacks", "reconciliation_note")
    op.drop_column("bid_writebacks", "reconciliation_result")
    op.drop_index("ix_bid_writebacks_approval_id", table_name="bid_writebacks")
    op.drop_constraint("fk_bid_writebacks_approval_id", "bid_writebacks", type_="foreignkey")
    op.drop_column("bid_writebacks", "approval_id")
    op.drop_column("baidu_oauth_states", "bind_to_tenant")
