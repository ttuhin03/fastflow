"""Add orchestrator_settings table for persistent UI settings

Revision ID: 015_add_orchestrator_settings
Revises: 014_add_pipeline_runs_indexes
Create Date: 2025-02-02

Persistent settings from Settings UI. DB values override env at startup.
"""
from alembic import op
import sqlalchemy as sa

revision = "015_add_orchestrator_settings"
down_revision = "014_add_pipeline_runs_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orchestrator_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("log_retention_runs", sa.Integer(), nullable=True),
        sa.Column("log_retention_days", sa.Integer(), nullable=True),
        sa.Column("log_max_size_mb", sa.Integer(), nullable=True),
        sa.Column("max_concurrent_runs", sa.Integer(), nullable=True),
        sa.Column("container_timeout", sa.Integer(), nullable=True),
        sa.Column("retry_attempts", sa.Integer(), nullable=True),
        sa.Column("auto_sync_enabled", sa.Boolean(), nullable=True),
        sa.Column("auto_sync_interval", sa.Integer(), nullable=True),
        sa.Column("email_enabled", sa.Boolean(), nullable=True),
        sa.Column("smtp_host", sa.String(), nullable=True),
        sa.Column("smtp_port", sa.Integer(), nullable=True),
        sa.Column("smtp_user", sa.String(), nullable=True),
        sa.Column("smtp_password_encrypted", sa.String(), nullable=True),
        sa.Column("smtp_from", sa.String(), nullable=True),
        sa.Column("email_recipients", sa.Text(), nullable=True),
        sa.Column("teams_enabled", sa.Boolean(), nullable=True),
        sa.Column("teams_webhook_url", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(sa.text("INSERT INTO orchestrator_settings (id) VALUES (1)"))


def downgrade() -> None:
    op.drop_table("orchestrator_settings")
