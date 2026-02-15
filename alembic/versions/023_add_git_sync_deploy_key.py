"""Add git_sync_deploy_key_encrypted to orchestrator_settings

Revision ID: 023_add_git_sync_deploy_key
Revises: 022_add_pipelines_subdir
Create Date: 2025-02-14

Deploy Key (privater SSH-Key) für Git-Sync per SSH-URL als Alternative zum PAT.
"""
from alembic import op
import sqlalchemy as sa

revision = "023_add_git_sync_deploy_key"
down_revision = "022_add_pipelines_subdir"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orchestrator_settings",
        sa.Column("git_sync_deploy_key_encrypted", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orchestrator_settings", "git_sync_deploy_key_encrypted")
