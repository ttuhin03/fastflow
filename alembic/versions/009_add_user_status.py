"""Add users.status for Beitrittsanfragen (pending/active/rejected)

Revision ID: 009_add_user_status
Revises: 008_add_google_avatar
Create Date: 2024-01-18 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "009_add_user_status"
down_revision = "008_add_google_avatar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("status", sa.String(), nullable=False, server_default="active"))


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("status")
