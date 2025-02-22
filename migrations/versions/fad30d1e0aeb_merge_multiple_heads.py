"""merge multiple heads

Revision ID: fad30d1e0aeb
Revises: 6bcac961ce38, b1648fbc8756
Create Date: 2025-02-22 23:46:59.975285

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fad30d1e0aeb'
down_revision = ('6bcac961ce38', 'b1648fbc8756')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
