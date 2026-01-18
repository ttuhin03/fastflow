"""Make users.password_hash nullable for GitHub OAuth users

Revision ID: 005_make_password_hash_nullable
Revises: 004_github_invitation
Create Date: 2024-01-18 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "005_make_password_hash_nullable"
down_revision = "004_github_invitation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "password_hash",
            existing_type=sa.String(),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "password_hash",
            existing_type=sa.String(),
            nullable=False,
        )
