"""Add last_login_at to users

Revision ID: 040_add_user_last_login
Revises: 039_add_ephemeral_tokens
Create Date: 2026-07-31

Zeitpunkt der letzten erfolgreichen Anmeldung. Bestehende Nutzer starten mit
NULL ("noch nie angemeldet"), der Wert wird beim nächsten Login gesetzt.
"""
from alembic import op
import sqlalchemy as sa

revision = "040_add_user_last_login"
down_revision = "039_add_ephemeral_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "last_login_at")
