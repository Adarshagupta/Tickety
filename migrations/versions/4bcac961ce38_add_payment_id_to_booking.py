"""add_payment_id_to_booking

Revision ID: 4bcac961ce38
Revises: 3bcac961ce38
Create Date: 2025-02-22 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '4bcac961ce38'
down_revision = '3bcac961ce38'
branch_labels = None
depends_on = None

def upgrade():
    # Add payment_id column to booking table
    with op.batch_alter_table('booking', schema=None) as batch_op:
        batch_op.add_column(sa.Column('payment_id', sa.String(length=100), nullable=True))

def downgrade():
    # Remove payment_id column from booking table
    with op.batch_alter_table('booking', schema=None) as batch_op:
        batch_op.drop_column('payment_id') 