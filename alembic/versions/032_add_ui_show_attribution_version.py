"""Add ui_show_attribution and ui_show_version to system_settings

Revision ID: 032_add_ui_show_attribution_version
Revises: 031_add_login_branding_logo_url
Create Date: 2026-03-29

"""
from alembic import op
import sqlalchemy as sa

revision = "032_add_ui_show_attribution_version"
down_revision = "031_add_login_branding_logo_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column(
            "ui_show_attribution",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "ui_show_version",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "ui_show_version")
    op.drop_column("system_settings", "ui_show_attribution")
