"""Add notification API: notification_api_keys table and orchestrator_settings columns

Revision ID: 026_add_notification_api
Revises: 025_add_pipeline_daily_stats
Create Date: 2025-02-26

Notification API for scripts: keys (hashed), feature toggle and rate limit in settings.
"""
from alembic import op
import sqlalchemy as sa

revision = "026_add_notification_api"
down_revision = "025_add_pipeline_daily_stats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New table for API keys (key_hash, label, created_at)
    op.create_table(
        "notification_api_keys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key_hash", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notification_api_keys_key_hash", "notification_api_keys", ["key_hash"], unique=False)

    # Add columns to orchestrator_settings
    op.add_column("orchestrator_settings", sa.Column("notification_api_enabled", sa.Boolean(), nullable=True))
    op.add_column("orchestrator_settings", sa.Column("notification_api_rate_limit_per_minute", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_index("ix_notification_api_keys_key_hash", table_name="notification_api_keys")
    op.drop_table("notification_api_keys")
    op.drop_column("orchestrator_settings", "notification_api_rate_limit_per_minute")
    op.drop_column("orchestrator_settings", "notification_api_enabled")
