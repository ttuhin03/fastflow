"""Add ui_login_background to system_settings

Revision ID: 034_add_ui_login_background
Revises: 033_add_show_unconfigured_oauth_on_login
Create Date: 2026-03-30

"""
from alembic import op
import sqlalchemy as sa

revision = "034_add_ui_login_background"
down_revision = "033_add_show_unconfigured_oauth_on_login"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column(
            "ui_login_background",
            sa.String(),
            nullable=False,
            server_default="video",
        ),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "ui_login_background")
