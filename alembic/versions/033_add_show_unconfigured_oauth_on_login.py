"""Add show_unconfigured_oauth_on_login to system_settings

Revision ID: 033_add_show_unconfigured_oauth_on_login
Revises: 032_add_ui_show_attribution_version
Create Date: 2026-03-29

"""
from alembic import op
import sqlalchemy as sa

revision = "033_add_show_unconfigured_oauth_on_login"
down_revision = "032_add_ui_show_attribution_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column(
            "show_unconfigured_oauth_on_login",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "show_unconfigured_oauth_on_login")
