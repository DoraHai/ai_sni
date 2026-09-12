"""Durable SEO QA batch queue; additive SEO-only table."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision = '0094_seo_qa_batches'
down_revision = '0093_seo_qa'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('seo_qa_batches',
        sa.Column('id',sa.BigInteger(),primary_key=True),
        sa.Column('tenant_id',sa.BigInteger(),sa.ForeignKey('tenants.id',ondelete='CASCADE'),nullable=False),
        sa.Column('site_id',sa.BigInteger(),sa.ForeignKey('seo_sites.id',ondelete='CASCADE'),nullable=False),
        sa.Column('actor',sa.String(64),nullable=False),
        sa.Column('request_key',sa.String(64),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('status',sa.String(24),nullable=False),
        sa.Column('items',JSONB(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.UniqueConstraint('tenant_id','site_id','actor','request_key',name='uq_seo_qa_batch_request'))
    for column in ('tenant_id','site_id','status'):
        op.create_index('ix_seo_qa_batches_'+column,'seo_qa_batches',[column])


def downgrade():
    op.drop_table('seo_qa_batches')
