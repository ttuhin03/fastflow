"""Add api_tokens table

Revision ID: 041_add_api_tokens
Revises: 040_add_user_last_login
Create Date: 2026-09-13

Persönliche API-Tokens für nicht-interaktive Clients (CI, Skripte, MCP).
Gespeichert wird nur der SHA-256-Digest des Tokens; der Klartext existiert
ausschließlich in der Antwort des erzeugenden Requests.
"""
from alembic import op
import sqlalchemy as sa

revision = "041_add_api_tokens"
down_revision = "040_add_user_last_login"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("prefix", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        # JSON statt einer Join-Tabelle: Scopes werden immer als Ganzes gelesen
        # und geschrieben, nie einzeln abgefragt.
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # token_hash ist der einzige Nachschlage-Pfad im Auth-Hotpath -> unique index.
    op.create_index("ix_api_tokens_token_hash", "api_tokens", ["token_hash"], unique=True)
    # user_id: Auflisten der eigenen Tokens; expires_at: Aufräum-/Reporting-Queries.
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"], unique=False)
    op.create_index("ix_api_tokens_expires_at", "api_tokens", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_api_tokens_expires_at", table_name="api_tokens")
    op.drop_index("ix_api_tokens_user_id", table_name="api_tokens")
    op.drop_index("ix_api_tokens_token_hash", table_name="api_tokens")
    op.drop_table("api_tokens")
