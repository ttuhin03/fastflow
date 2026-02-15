"""Set dependency_audit_enabled default to True

Revision ID: 024_dependency_audit_enabled_default_true
Revises: 023_add_git_sync_deploy_key
Create Date: 2025-02-15

Automatische Sicherheitsprüfung (täglich) soll standardmäßig aktiviert sein.
"""
from alembic import op
import sqlalchemy as sa

revision = "024_dependency_audit_enabled_default_true"
down_revision = "023_add_git_sync_deploy_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text("UPDATE system_settings SET dependency_audit_enabled = true WHERE id = 1")
    )
    op.alter_column(
        "system_settings",
        "dependency_audit_enabled",
        existing_type=sa.Boolean(),
        server_default=sa.true(),
    )


def downgrade() -> None:
    op.alter_column(
        "system_settings",
        "dependency_audit_enabled",
        existing_type=sa.Boolean(),
        server_default=sa.false(),
    )
