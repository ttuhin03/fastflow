"""Add on_route to downstream_triggers

Revision ID: 029_add_on_route_to_downstream_triggers
Revises: 028_add_audit_log
Create Date: 2026-03-10

Adds on_route column to downstream_triggers table.
Allows triggering a downstream pipeline based on a route string
written by the pipeline code to FASTFLOW_ROUTE_FILE.
"""
from alembic import op
import sqlalchemy as sa

revision = "029_add_on_route_to_downstream_triggers"
down_revision = "028_add_audit_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "downstream_triggers",
        sa.Column("on_route", sa.String(128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("downstream_triggers", "on_route")
