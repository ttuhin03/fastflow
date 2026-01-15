"""Add user management fields to User model

Revision ID: 003_add_user_management_fields
Revises: 002_add_webhook_fields
Create Date: 2024-01-03 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite


# revision identifiers, used by Alembic.
revision = '003_add_user_management_fields'
down_revision = '002_add_webhook_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make password_hash nullable (for Microsoft OAuth users)
    # SQLite requires batch_alter_table for adding columns
    with op.batch_alter_table('users', schema=None) as batch_op:
        # Add new columns
        batch_op.add_column(sa.Column('email', sa.String(), nullable=True))
        # Use uppercase 'READONLY' to match Enum values
        batch_op.add_column(sa.Column('role', sa.String(), nullable=False, server_default='READONLY'))
        batch_op.add_column(sa.Column('blocked', sa.Boolean(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('invitation_token', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('invitation_expires_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('microsoft_id', sa.String(), nullable=True))
    
    # Note: Data migration for lowercase enum values is handled in application code
    # (see app/auth.py get_or_create_user and get_current_user functions)
    # This avoids hanging migrations with SQLite
    
    # Note: Indexes are created automatically by SQLModel based on Field(index=True)
    # No need to create them manually here to avoid hanging


def downgrade() -> None:
    # Drop indexes
    op.drop_index(op.f('ix_users_microsoft_id'), table_name='users')
    op.drop_index(op.f('ix_users_invitation_token'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    
    # Remove columns
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('microsoft_id')
        batch_op.drop_column('invitation_expires_at')
        batch_op.drop_column('invitation_token')
        batch_op.drop_column('blocked')
        batch_op.drop_column('role')
        batch_op.drop_column('email')
