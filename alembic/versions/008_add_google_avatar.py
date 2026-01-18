"""Add users.google_id and users.avatar_url for Google OAuth

Revision ID: 008_add_google_avatar
Revises: 007_drop_password_hash
Create Date: 2024-01-18 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "008_add_google_avatar"
down_revision = "007_drop_password_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("google_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("avatar_url", sa.String(), nullable=True))
    op.create_index(op.f("ix_users_google_id"), "users", ["google_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_google_id"), table_name="users")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("avatar_url")
        batch_op.drop_column("google_id")
