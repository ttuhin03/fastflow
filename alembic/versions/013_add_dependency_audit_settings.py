"""Add dependency_audit_enabled and dependency_audit_cron to system_settings

Revision ID: 013_add_dependency_audit_settings
Revises: 012_add_run_cell_log
Create Date: 2025-01-30

"""
from alembic import op
import sqlalchemy as sa

revision = "013_add_dependency_audit_settings"
down_revision = "012_add_run_cell_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("dependency_audit_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "system_settings",
        sa.Column("dependency_audit_cron", sa.String(), nullable=False, server_default=sa.text("'0 3 * * *'")),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "dependency_audit_cron")
    op.drop_column("system_settings", "dependency_audit_enabled")
