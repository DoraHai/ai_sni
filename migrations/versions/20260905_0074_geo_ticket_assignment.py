"""Add optional owner and deadline to GEO action tickets only."""
from alembic import op
import sqlalchemy as sa

revision = '0074_geo_ticket_assignment'
down_revision = '0073_geo_schema_repair'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('geo_action_tickets', sa.Column('owner_name', sa.String(100), nullable=True))
    op.add_column('geo_action_tickets', sa.Column('due_date', sa.Date(), nullable=True))


def downgrade():
    op.drop_column('geo_action_tickets', 'due_date')
    op.drop_column('geo_action_tickets', 'owner_name')
