"""Phase1a shadow-only storage and explicit per-account bindings; never auto-run.

No permissions are granted to sem_runtime. Account bindings must be provisioned by
an independently authorized workflow; this slice supplies no grant-writing endpoint.
"""
from alembic import op
import sqlalchemy as sa

revision = '0077_sem_phase1a_shadow'
down_revision = '0076_oauth_rebind_intent'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('sem_phase1a_account_grants',
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('tenant_id', sa.BigInteger(), sa.ForeignKey('tenants.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('baidu_accounts.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('advisor_grant_id', sa.BigInteger(), sa.ForeignKey('advisor_tenant_grants.id', ondelete='RESTRICT')),
        sa.Column('revoked_at', sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint('user_id', 'account_id', name='pk_sem_phase1a_account_grants'))
    for name in ('sem_phase1a_shadow_plans', 'sem_phase1a_shadow_previews'):
        op.create_table(name,
            sa.Column('id', sa.String(32), primary_key=True),
            sa.Column('revision', sa.BigInteger(), nullable=False),
            sa.Column('payload', sa.Text(), nullable=False),
            sa.Column('expires_at', sa.Float()),
            sa.CheckConstraint('revision > 0', name='ck_' + name + '_revision'))
    op.create_index('ix_sem_phase1a_preview_expiry', 'sem_phase1a_shadow_previews', ['expires_at'])


def downgrade():
    raise RuntimeError('第三刀迁移只加不删；禁止downgrade')
