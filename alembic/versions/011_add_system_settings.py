"""Add system_settings table for PostHog Error-Tracking (Phase 1) and future telemetry

Revision ID: 011_add_system_settings
Revises: 010_add_github_login
Create Date: 2024-01-19 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "011_add_system_settings"
down_revision = "010_add_github_login"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("is_setup_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enable_telemetry", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enable_error_reporting", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("telemetry_distinct_id", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # SQLite: 0; PostgreSQL: 0 may fail for boolean, but server_default in add_column uses 0. Kept 0 for SQLite.
    op.execute(
        sa.text(
            "INSERT INTO system_settings (id, is_setup_completed, enable_telemetry, enable_error_reporting) "
            "VALUES (1, 0, 0, 0)"
        )
    )


def downgrade() -> None:
    op.drop_table("system_settings")
