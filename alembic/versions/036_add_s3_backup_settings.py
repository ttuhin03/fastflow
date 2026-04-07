"""Add S3 backup settings to orchestrator_settings

Revision ID: 036_add_s3_backup_settings
Revises: 035_add_ui_header_timezones
Create Date: 2026-04-07
"""
from alembic import op
import sqlalchemy as sa

revision = "036_add_s3_backup_settings"
down_revision = "035_add_ui_header_timezones"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orchestrator_settings", sa.Column("s3_backup_enabled", sa.Boolean(), nullable=True))
    op.add_column("orchestrator_settings", sa.Column("s3_endpoint_url", sa.String(), nullable=True))
    op.add_column("orchestrator_settings", sa.Column("s3_bucket", sa.String(), nullable=True))
    op.add_column("orchestrator_settings", sa.Column("s3_access_key_encrypted", sa.Text(), nullable=True))
    op.add_column("orchestrator_settings", sa.Column("s3_secret_access_key_encrypted", sa.Text(), nullable=True))
    op.add_column("orchestrator_settings", sa.Column("s3_region", sa.String(), nullable=True))
    op.add_column("orchestrator_settings", sa.Column("s3_prefix", sa.String(), nullable=True))
    op.add_column("orchestrator_settings", sa.Column("s3_use_path_style", sa.Boolean(), nullable=True))
    op.add_column("orchestrator_settings", sa.Column("s3_last_test_at", sa.DateTime(), nullable=True))
    op.add_column("orchestrator_settings", sa.Column("s3_last_test_status", sa.String(), nullable=True))
    op.add_column("orchestrator_settings", sa.Column("s3_last_test_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("orchestrator_settings", "s3_last_test_error")
    op.drop_column("orchestrator_settings", "s3_last_test_status")
    op.drop_column("orchestrator_settings", "s3_last_test_at")
    op.drop_column("orchestrator_settings", "s3_use_path_style")
    op.drop_column("orchestrator_settings", "s3_prefix")
    op.drop_column("orchestrator_settings", "s3_region")
    op.drop_column("orchestrator_settings", "s3_secret_access_key_encrypted")
    op.drop_column("orchestrator_settings", "s3_access_key_encrypted")
    op.drop_column("orchestrator_settings", "s3_bucket")
    op.drop_column("orchestrator_settings", "s3_endpoint_url")
    op.drop_column("orchestrator_settings", "s3_backup_enabled")
