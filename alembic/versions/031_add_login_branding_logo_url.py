"""Add login_branding_logo_url to system_settings

Revision ID: 031_add_login_branding_logo_url
Revises: 030_add_audit_log_created_at_index
Create Date: 2026-03-29

"""
from alembic import op
import sqlalchemy as sa

revision = "031_add_login_branding_logo_url"
down_revision = "030_add_audit_log_created_at_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("login_branding_logo_url", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "login_branding_logo_url")
