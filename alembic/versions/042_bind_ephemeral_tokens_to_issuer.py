"""Bind ephemeral tokens to their issuer

Revision ID: 042_bind_ephemeral_tokens
Revises: 041_add_api_tokens
Create Date: 2026-09-13

Log-Download-Tokens waren an nichts als die run_id gebunden: 60 Sekunden lang,
mehrfach nutzbar, ohne Bezug zum Aussteller. Wer vor einem Widerruf eine Handvoll
Download-URLs auf Vorrat holte, las danach ohne jede Credential weiter.
Mit issued_to_user_id und issued_via_api_token_id lässt sich beim Einlösen
prüfen, ob Nutzer und Token noch gültig sind.
"""
from alembic import op
import sqlalchemy as sa

revision = "042_bind_ephemeral_tokens"
down_revision = "041_add_api_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable: Bestandszeilen haben keinen Aussteller. Sie laufen nach 60
    # Sekunden ohnehin ab, eine Datenmigration wäre also Aufwand ohne Wirkung.
    op.add_column("ephemeral_tokens", sa.Column("issued_to_user_id", sa.Uuid(), nullable=True))
    op.add_column(
        "ephemeral_tokens", sa.Column("issued_via_api_token_id", sa.Uuid(), nullable=True)
    )
    op.create_index(
        "ix_ephemeral_tokens_issued_to_user_id",
        "ephemeral_tokens",
        ["issued_to_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_ephemeral_tokens_issued_via_api_token_id",
        "ephemeral_tokens",
        ["issued_via_api_token_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ephemeral_tokens_issued_via_api_token_id", table_name="ephemeral_tokens")
    op.drop_index("ix_ephemeral_tokens_issued_to_user_id", table_name="ephemeral_tokens")
    op.drop_column("ephemeral_tokens", "issued_via_api_token_id")
    op.drop_column("ephemeral_tokens", "issued_to_user_id")
