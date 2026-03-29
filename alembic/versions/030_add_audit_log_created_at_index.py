"""Add index on audit_log.created_at for performance

Revision ID: 030_add_audit_log_created_at_index
Revises: 029_add_on_route_to_downstream_triggers
Create Date: 2026-03-23

Index for common query patterns:
- created_at: ORDER BY and date-range filters in audit log queries
"""
from alembic import op

revision = "030_add_audit_log_created_at_index"
down_revision = "029_add_on_route_to_downstream_triggers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Index ix_audit_log_created_at is already created in 028_add_audit_log.
    # This revision remains for deployments that stamped 029 without 030; no-op avoids duplicate index errors.
    pass


def downgrade() -> None:
    # Do not drop: index is owned by 028_add_audit_log.
    pass
