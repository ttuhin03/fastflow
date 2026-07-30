"""Add ephemeral_tokens table

Revision ID: 039_add_ephemeral_tokens
Revises: 038_add_audit_ip_address
Create Date: 2026-07-09

DB-backed, short-TTL tokens for account-link and log-download flows
(replaces self-verifying JWTs for these flows; see TE-15).
"""
from alembic import op
import sqlalchemy as sa

revision = "039_add_ephemeral_tokens"
down_revision = "038_add_audit_ip_address"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ephemeral_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("token_type", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ephemeral_tokens_token", "ephemeral_tokens", ["token"], unique=True)
    op.create_index("ix_ephemeral_tokens_subject", "ephemeral_tokens", ["subject"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ephemeral_tokens_subject", table_name="ephemeral_tokens")
    op.drop_index("ix_ephemeral_tokens_token", table_name="ephemeral_tokens")
    op.drop_table("ephemeral_tokens")
