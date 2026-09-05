"""SEO task contracts and durable image verification queue."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision='0092_seo_cockpit'
down_revision='0091_seo_backlink_evidence'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('seo_tasks',
        sa.Column('id',sa.BigInteger(),primary_key=True),
        sa.Column('tenant_id',sa.BigInteger(),sa.ForeignKey('tenants.id',ondelete='CASCADE'),nullable=False),
        sa.Column('site_id',sa.BigInteger(),sa.ForeignKey('seo_sites.id',ondelete='CASCADE'),nullable=False),
        sa.Column('module',sa.String(3),nullable=False),sa.Column('action_type',sa.String(64),nullable=False),
        sa.Column('title',sa.String(240),nullable=False),sa.Column('params',postgresql.JSONB(),nullable=False),
        sa.Column('status',sa.String(16),nullable=False),sa.Column('created_by',sa.String(64),nullable=False),
        sa.Column('assignee_role',sa.String(80),nullable=False),sa.Column('completion_evidence',postgresql.JSONB()),
        sa.Column('baseline',postgresql.JSONB(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.CheckConstraint("module = 'seo'",name='ck_seo_task_module'),
        sa.CheckConstraint("status IN ('open','in_progress','done','cancelled')",name='ck_seo_task_status'))
    op.create_index('ix_seo_task_scope','seo_tasks',['tenant_id','site_id','status'])
    op.create_table('seo_image_verifications',
        sa.Column('id',sa.BigInteger(),primary_key=True),
        sa.Column('tenant_id',sa.BigInteger(),sa.ForeignKey('tenants.id',ondelete='CASCADE'),nullable=False),
        sa.Column('site_id',sa.BigInteger(),sa.ForeignKey('seo_sites.id',ondelete='CASCADE'),nullable=False),
        sa.Column('page_id',sa.BigInteger(),sa.ForeignKey('seo_site_pages.id',ondelete='CASCADE'),nullable=False),
        sa.Column('review_id',sa.BigInteger(),sa.ForeignKey('seo_image_alt_reviews.id',ondelete='CASCADE'),nullable=False),
        sa.Column('status',sa.String(20),nullable=False),sa.Column('approved_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('checked_at',sa.DateTime(timezone=True)),
        sa.Column('available_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column('evidence',postgresql.JSONB()),
        sa.Column('result_snapshot_id',sa.BigInteger(),sa.ForeignKey('seo_page_snapshots.id',ondelete='RESTRICT')),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.CheckConstraint("status IN ('pending','checking','verified','unverified','unavailable','superseded')",name='ck_seo_image_verification_status'))
    op.create_index('ix_seo_image_verification_due','seo_image_verifications',['status','available_at'])
    op.create_index('ix_seo_image_verification_scope','seo_image_verifications',['tenant_id','site_id','review_id'])

def downgrade():
    op.drop_table('seo_image_verifications')
    op.drop_table('seo_tasks')
