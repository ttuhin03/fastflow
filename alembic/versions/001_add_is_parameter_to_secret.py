"""Add is_parameter field to Secret model

Revision ID: 001_add_is_parameter
Revises: 
Create Date: 2024-01-01 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001_add_is_parameter'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add is_parameter column to secrets table
    # SQLite requires batch mode for adding columns
    with op.batch_alter_table('secrets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_parameter', sa.Boolean(), nullable=False, server_default='0'))


def downgrade() -> None:
    # Remove is_parameter column from secrets table
    with op.batch_alter_table('secrets', schema=None) as batch_op:
        batch_op.drop_column('is_parameter')
