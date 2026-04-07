"""Add s3_test_on_save to orchestrator_settings

Revision ID: 037_add_s3_test_on_save
Revises: 036_add_s3_backup_settings
Create Date: 2026-04-07
"""
from alembic import op
import sqlalchemy as sa

revision = "037_add_s3_test_on_save"
down_revision = "036_add_s3_backup_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orchestrator_settings",
        sa.Column("s3_test_on_save", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orchestrator_settings", "s3_test_on_save")
