"""Drop obsolete users.invitation_token and users.invitation_expires_at

Einladungen laufen nur noch über die Tabelle invitations.
Invitation-Token und -Ablauf gehörten zum alten Passwort-Accept-Flow.

Revision ID: 006_drop_user_invitation_columns
Revises: 005_make_password_hash_nullable
Create Date: 2024-01-18 19:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "006_drop_user_invitation_columns"
down_revision = "005_make_password_hash_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Zuerst Index entfernen (SQLite batch rec recreiert Tabelle, Spalte+Index weg)
    try:
        op.drop_index(op.f("ix_users_invitation_token"), table_name="users")
    except Exception:
        pass  # Index kann bereits fehlen
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("invitation_token")
        batch_op.drop_column("invitation_expires_at")


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("invitation_expires_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("invitation_token", sa.String(), nullable=True))
        batch_op.create_index("ix_users_invitation_token", ["invitation_token"], unique=True)

