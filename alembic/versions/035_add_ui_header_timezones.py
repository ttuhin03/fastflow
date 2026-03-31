"""Add ui_header_timezone_1/2 to system_settings

Revision ID: 035_add_ui_header_timezones
Revises: 034_add_ui_login_background
Create Date: 2026-03-31

"""
from alembic import op
import sqlalchemy as sa

revision = "035_add_ui_header_timezones"
down_revision = "034_add_ui_login_background"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column(
            "ui_header_timezone_1",
            sa.String(),
            nullable=False,
            server_default="UTC",
        ),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "ui_header_timezone_2",
            sa.String(),
            nullable=False,
            server_default="Europe/Berlin",
        ),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "ui_header_timezone_2")
    op.drop_column("system_settings", "ui_header_timezone_1")
