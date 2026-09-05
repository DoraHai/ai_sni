"""SEO question workbench; adds SEO-owned tables only."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0093_seo_qa'
down_revision = '0092_seo_cockpit'
branch_labels = None
depends_on = None


def scope_columns():
    return [sa.Column('id', sa.BigInteger(), primary_key=True),
            sa.Column('tenant_id', sa.BigInteger(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
            sa.Column('site_id', sa.BigInteger(), sa.ForeignKey('seo_sites.id', ondelete='CASCADE'), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def upgrade():
    op.create_table('seo_questions', *scope_columns(),
        sa.Column('title', sa.String(300), nullable=False), sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('topic', sa.String(120), nullable=False), sa.Column('intent', sa.String(32), nullable=False),
        sa.Column('status', sa.String(24), nullable=False), sa.Column('relevance', sa.Integer(), nullable=False),
        sa.Column('owner', sa.String(120)), sa.Column('sources', JSONB(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.UniqueConstraint('tenant_id', 'site_id', 'fingerprint', name='uq_seo_question_scope'))
    op.create_table('seo_qa_facts', *scope_columns(),
        sa.Column('title', sa.String(240), nullable=False), sa.Column('statement', sa.Text(), nullable=False),
        sa.Column('source_name', sa.String(240), nullable=False), sa.Column('source_url', sa.Text()),
        sa.Column('expires_at', sa.DateTime(timezone=True)), sa.Column('status', sa.String(20), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False))
    op.create_table('seo_qa_answers', *scope_columns(),
        sa.Column('question_id', sa.BigInteger(), sa.ForeignKey('seo_questions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('content_id', sa.BigInteger(), sa.ForeignKey('seo_content_assets.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('format', sa.String(24), nullable=False), sa.Column('fact_snapshots', JSONB(), nullable=False),
        sa.Column('evidence_hash', sa.String(64), nullable=False))
    op.create_table('seo_qa_placements', *scope_columns(),
        sa.Column('answer_id', sa.BigInteger(), sa.ForeignKey('seo_qa_answers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('platform', sa.String(24), nullable=False), sa.Column('question_url', sa.Text()), sa.Column('answer_url', sa.Text()),
        sa.Column('status', sa.String(24), nullable=False), sa.Column('scheduled_at', sa.DateTime(timezone=True)),
        sa.Column('content_version', sa.Integer(), nullable=False), sa.Column('body', sa.Text(), nullable=False),
        sa.Column('observations', JSONB(), nullable=False), sa.Column('reported_metrics', JSONB()),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.UniqueConstraint('answer_id', 'platform', 'content_version', name='uq_seo_qa_placement_version'))
    for table in ['seo_questions', 'seo_qa_facts', 'seo_qa_answers', 'seo_qa_placements']:
        for column in ['tenant_id', 'site_id']:
            op.create_index(f'ix_{table}_{column}', table, [column])
    op.create_index('ix_seo_qa_answers_question_id', 'seo_qa_answers', ['question_id'])
    op.create_index('ix_seo_qa_placements_answer_id', 'seo_qa_placements', ['answer_id'])


def downgrade():
    for table in ['seo_qa_placements', 'seo_qa_answers', 'seo_qa_facts', 'seo_questions']:
        op.drop_table(table)
