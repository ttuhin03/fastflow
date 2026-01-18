"""Drop users.password_hash

Login nur noch via GitHub OAuth. Die Spalte wird nicht mehr benötigt.

Revision ID: 007_drop_password_hash
Revises: 006_drop_user_invitation_columns
Create Date: 2024-01-18 20:00:00.000000

"""
from alembic import op


revision = "007_drop_password_hash"
down_revision = "006_drop_user_invitation_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("password_hash")


def downgrade() -> None:
    import sqlalchemy as sa
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("password_hash", sa.String(), nullable=True))
