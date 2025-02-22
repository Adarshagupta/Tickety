"""fix_check_in_columns

Revision ID: 5bcac961ce38
Revises: 4bcac961ce38
Create Date: 2025-02-22 18:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '5bcac961ce38'
down_revision = '4bcac961ce38'
branch_labels = None
depends_on = None

def upgrade():
    # Add new columns
    with op.batch_alter_table('booking', schema=None) as batch_op:
        batch_op.add_column(sa.Column('checked_in_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('refunded_at', sa.DateTime(), nullable=True))

def downgrade():
    # Remove the new columns
    with op.batch_alter_table('booking', schema=None) as batch_op:
        batch_op.drop_column('checked_in_at')
        batch_op.drop_column('refunded_at') 