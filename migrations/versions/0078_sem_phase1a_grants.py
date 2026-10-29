"""Account/tenant integrity and audited shadow grant management. Additive only.

PostgreSQL uses a composite FK; the redundant unique index is safe logically
because account id is already a PK, but still requires an operational lock/size
review before any separately authorized production upgrade. SQLite uses equivalent
insert/update and parent-update triggers without rebuilding or dropping tables.
"""
from alembic import op
import sqlalchemy as sa

revision = '0078_sem_phase1a_grants'
down_revision = '0077_sem_phase1a_shadow'
branch_labels = None
depends_on = None


def upgrade():
    db = op.get_bind()
    # Refuse pre-existing invalid bindings; never silently repair/delete data.
    invalid = db.execute(sa.text('SELECT 1 FROM sem_phase1a_account_grants g '
        'LEFT JOIN baidu_accounts a ON a.id=g.account_id AND a.tenant_id=g.tenant_id '
        'WHERE a.id IS NULL LIMIT 1')).first()
    if invalid:
        raise RuntimeError('账户绑定完整性检查未通过，停止迁移')
    if db.dialect.name == 'postgresql':
        op.create_index('uq_sem_phase1a_account_tenant', 'baidu_accounts', ['id', 'tenant_id'], unique=True)
        op.create_foreign_key('fk_sem_phase1a_grant_account_tenant', 'sem_phase1a_account_grants',
                             'baidu_accounts', ['account_id', 'tenant_id'], ['id', 'tenant_id'], ondelete='RESTRICT')
    elif db.dialect.name == 'sqlite':
        for action in ('INSERT', 'UPDATE'):
            op.execute(sa.text('CREATE TRIGGER ck_sem_phase1a_grant_tenant_' + action.lower() +
                ' BEFORE ' + action + ' ON sem_phase1a_account_grants '
                'WHEN NOT EXISTS (SELECT 1 FROM baidu_accounts WHERE id=NEW.account_id AND tenant_id=NEW.tenant_id) '
                "BEGIN SELECT RAISE(ABORT, 'account tenant mismatch'); END"))
        op.execute(sa.text('CREATE TRIGGER ck_sem_phase1a_account_tenant_update '
            'BEFORE UPDATE OF id,tenant_id ON baidu_accounts '
            'WHEN EXISTS (SELECT 1 FROM sem_phase1a_account_grants '
            'WHERE account_id=OLD.id AND (account_id!=NEW.id OR tenant_id!=NEW.tenant_id)) '
            "BEGIN SELECT RAISE(ABORT, 'account tenant mismatch'); END"))
    else:
        raise RuntimeError('不支持的迁移数据库')
    op.add_column('sem_phase1a_account_grants', sa.Column('generation', sa.BigInteger(), nullable=False, server_default='0'))
    op.create_table('sem_phase1a_grant_audit',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('actor_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('tenant_id', sa.BigInteger(), sa.ForeignKey('tenants.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('baidu_accounts.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('advisor_grant_id', sa.BigInteger(), sa.ForeignKey('advisor_tenant_grants.id', ondelete='RESTRICT')),
        sa.Column('generation', sa.BigInteger(), nullable=False),
        sa.Column('action', sa.String(16), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("action IN ('grant','revoke')", name='ck_sem_phase1a_grant_audit_action'),
        sa.CheckConstraint('generation >= 0', name='ck_sem_phase1a_grant_audit_generation'))


def downgrade():
    raise RuntimeError('第四刀迁移只加不删；禁止downgrade')
