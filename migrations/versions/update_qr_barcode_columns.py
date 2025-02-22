"""update_qr_barcode_columns

Revision ID: update_qr_barcode_columns
Revises: 2bcac961ce38
Create Date: 2025-02-22 16:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'update_qr_barcode_columns'
down_revision = '2bcac961ce38'
branch_labels = None
depends_on = None

def upgrade():
    # Change column types to Text for unlimited length
    with op.batch_alter_table('booking', schema=None) as batch_op:
        batch_op.alter_column('qr_code',
               existing_type=sa.String(length=500),
               type_=sa.Text(),
               existing_nullable=True)
        batch_op.alter_column('barcode',
               existing_type=sa.String(length=500),
               type_=sa.Text(),
               existing_nullable=True)

def downgrade():
    # Revert column types back to String(500)
    with op.batch_alter_table('booking', schema=None) as batch_op:
        batch_op.alter_column('qr_code',
               existing_type=sa.Text(),
               type_=sa.String(length=500),
               existing_nullable=True)
        batch_op.alter_column('barcode',
               existing_type=sa.Text(),
               type_=sa.String(length=500),
               existing_nullable=True) 