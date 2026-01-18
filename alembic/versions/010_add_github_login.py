"""Add users.github_login for correct GitHub profile links

Revision ID: 010_add_github_login
Revises: 009_add_user_status
Create Date: 2024-01-18 23:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "010_add_github_login"
down_revision = "009_add_user_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("github_login", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("github_login")
