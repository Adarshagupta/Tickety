"""add_share_id_to_booking

Revision ID: 6bcac961ce38
Revises: 5bcac961ce38
Create Date: 2025-02-22 19:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import secrets

# revision identifiers, used by Alembic.
revision = '6bcac961ce38'
down_revision = '5bcac961ce38'
branch_labels = None
depends_on = None

def generate_share_id():
    return secrets.token_urlsafe(16)

def upgrade():
    # Add share_id column
    with op.batch_alter_table('booking', schema=None) as batch_op:
        batch_op.add_column(sa.Column('share_id', sa.String(length=32), nullable=True))
        batch_op.create_unique_constraint('uq_booking_share_id', ['share_id'])
    
    # Generate share_ids for existing bookings
    connection = op.get_bind()
    bookings = connection.execute(sa.text('SELECT id FROM booking')).fetchall()
    
    for booking_id in bookings:
        share_id = generate_share_id()
        # Keep generating until we get a unique share_id
        while connection.execute(
            sa.text('SELECT id FROM booking WHERE share_id = :share_id'),
            {'share_id': share_id}
        ).fetchone() is not None:
            share_id = generate_share_id()
            
        connection.execute(
            sa.text('UPDATE booking SET share_id = :share_id WHERE id = :id'),
            {'share_id': share_id, 'id': booking_id[0]}
        )
    
    # Make share_id non-nullable after populating data
    with op.batch_alter_table('booking', schema=None) as batch_op:
        batch_op.alter_column('share_id', nullable=False)

def downgrade():
    with op.batch_alter_table('booking', schema=None) as batch_op:
        batch_op.drop_constraint('uq_booking_share_id', type_='unique')
        batch_op.drop_column('share_id') 