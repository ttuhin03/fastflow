"""GitHub OAuth + Invitation: invitations table, users.github_id

Revision ID: 004_github_invitation
Revises: 003_add_user_management_fields
Create Date: 2024-01-03 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "004_github_invitation"
down_revision = "003_add_user_management_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tabelle invitations (Token-Einladung für GitHub OAuth)
    op.create_table(
        "invitations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("recipient_email", sa.String(), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("is_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="READONLY"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(op.f("ix_invitations_recipient_email"), "invitations", ["recipient_email"])
    op.create_index(op.f("ix_invitations_token"), "invitations", ["token"], unique=True)

    # Spalte github_id in users (nullable, unique, index)
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("github_id", sa.String(), nullable=True))
    op.create_index(op.f("ix_users_github_id"), "users", ["github_id"], unique=True)


def downgrade() -> None:
    # users.github_id entfernen
    op.drop_index(op.f("ix_users_github_id"), table_name="users")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("github_id")

    # Tabelle invitations entfernen
    op.drop_index(op.f("ix_invitations_token"), table_name="invitations")
    op.drop_index(op.f("ix_invitations_recipient_email"), table_name="invitations")
    op.drop_table("invitations")
