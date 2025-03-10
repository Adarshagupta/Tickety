"""Add wallet and transaction models

Revision ID: b1648fbc8756
Revises: 5bcac961ce38
Create Date: 2025-02-22 22:50:25.604761

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'b1648fbc8756'
down_revision = '5bcac961ce38'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('booking', schema=None) as batch_op:
        batch_op.alter_column('tier_id',
               existing_type=sa.VARCHAR(length=50),
               nullable=True)
        batch_op.alter_column('attendee_details',
               existing_type=postgresql.JSON(astext_type=sa.Text()),
               nullable=True)
        batch_op.alter_column('check_in_status',
               existing_type=sa.BOOLEAN(),
               nullable=True,
               existing_server_default=sa.text('false'))
        batch_op.alter_column('ticket_code',
               existing_type=sa.VARCHAR(length=20),
               nullable=True)
        batch_op.drop_constraint('booking_ticket_code_key', type_='unique')
        batch_op.drop_column('check_in_time')

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('booking', schema=None) as batch_op:
        batch_op.add_column(sa.Column('check_in_time', postgresql.TIMESTAMP(), autoincrement=False, nullable=True))
        batch_op.create_unique_constraint('booking_ticket_code_key', ['ticket_code'])
        batch_op.alter_column('ticket_code',
               existing_type=sa.VARCHAR(length=20),
               nullable=False)
        batch_op.alter_column('check_in_status',
               existing_type=sa.BOOLEAN(),
               nullable=False,
               existing_server_default=sa.text('false'))
        batch_op.alter_column('attendee_details',
               existing_type=postgresql.JSON(astext_type=sa.Text()),
               nullable=False)
        batch_op.alter_column('tier_id',
               existing_type=sa.VARCHAR(length=50),
               nullable=False)

    # ### end Alembic commands ###
