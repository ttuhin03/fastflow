"""Add custom_oauth_id to users for Custom OAuth (Keycloak, Auth0, etc.)

Revision ID: 018_add_custom_oauth_id
Revises: 017_add_downstream_triggers
Create Date: 2025-02-06

"""
from alembic import op
import sqlalchemy as sa

revision = "018_add_custom_oauth_id"
down_revision = "017_add_downstream_triggers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("custom_oauth_id", sa.String(), nullable=True),
    )
    op.create_index(
        op.f("ix_users_custom_oauth_id"),
        "users",
        ["custom_oauth_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_users_custom_oauth_id"), table_name="users")
    op.drop_column("users", "custom_oauth_id")
