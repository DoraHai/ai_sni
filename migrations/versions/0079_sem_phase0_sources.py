"""Versioned SEM sources and private attachment references. Additive only.

No data backfill, production configuration or runtime grants. Account composite
index on PostgreSQL already exists from 0078. SQLite gets an additive equivalent.
Immutable rows prevent rewriting source evidence, including by direct SQL.
"""
from alembic import op
import sqlalchemy as sa

revision = '0079_sem_phase0_sources'
down_revision = '0078_sem_phase1a_grants'
branch_labels = None
depends_on = None


def upgrade():
    db = op.get_bind()
    if db.dialect.name not in {'postgresql', 'sqlite'}:
        raise RuntimeError('不支持的迁移数据库')
    if db.dialect.name == 'sqlite':
        op.create_index('uq_sem_phase0_account_tenant', 'baidu_accounts', ['id', 'tenant_id'], unique=True)
    scope = ['tenant_id', 'account_id', 'page_id']
    def columns():
        return [sa.Column('tenant_id', sa.BigInteger(), nullable=False),
                sa.Column('account_id', sa.Integer(), nullable=False),
                sa.Column('page_id', sa.String(80), nullable=False)]
    op.create_table('sem_phase0_pages', *columns(),
        sa.Column('product_id', sa.String(80), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint(*scope),
        sa.ForeignKeyConstraint(['account_id', 'tenant_id'], ['baidu_accounts.id', 'baidu_accounts.tenant_id'],
                                name='fk_sem_phase0_page_account_tenant', ondelete='RESTRICT'))
    op.create_table('sem_phase0_submissions', *columns(),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('actor_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('submitted_at', sa.String(40), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('payload_sha256', sa.String(64), nullable=False),
        sa.Column('attachments_sha256', sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint(*scope, 'revision'),
        sa.ForeignKeyConstraint(scope, ['sem_phase0_pages.' + col for col in scope], ondelete='RESTRICT'),
        sa.CheckConstraint('revision > 0', name='ck_sem_phase0_revision'))
    op.create_table('sem_phase0_attachments', *columns(),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('object_key', sa.String(512), nullable=False, unique=True),
        sa.Column('metadata', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint(*scope, 'revision', 'ordinal'),
        sa.ForeignKeyConstraint(scope + ['revision'],
            ['sem_phase0_submissions.' + col for col in scope + ['revision']], ondelete='RESTRICT'),
        sa.CheckConstraint('ordinal BETWEEN 1 AND 10', name='ck_sem_phase0_attachment_ordinal'))
    if db.dialect.name == 'postgresql':
        op.execute(sa.text("CREATE FUNCTION sem_phase0_reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ "
                           "BEGIN RAISE EXCEPTION 'immutable SEM source'; END; $$"))
    for table in ('sem_phase0_pages', 'sem_phase0_submissions', 'sem_phase0_attachments'):
        if db.dialect.name == 'postgresql':
            op.execute(sa.text('CREATE TRIGGER immutable_' + table + ' BEFORE UPDATE OR DELETE ON ' + table +
                               ' FOR EACH ROW EXECUTE FUNCTION sem_phase0_reject_mutation()'))
        else:
            for action in ('UPDATE', 'DELETE'):
                op.execute(sa.text('CREATE TRIGGER immutable_' + table + '_' + action.lower() +
                    ' BEFORE ' + action + ' ON ' + table +
                    " BEGIN SELECT RAISE(ABORT, 'immutable SEM source'); END"))


def downgrade():
    raise RuntimeError('第五刀迁移只加不删；禁止downgrade')
