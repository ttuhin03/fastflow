"""Add git_sync_repo_url, git_sync_token_encrypted, git_sync_branch to orchestrator_settings

Revision ID: 021_add_git_sync_repo_config
Revises: 020_add_run_config_to_downstream_triggers
Create Date: 2025-02-13

Repository URL + PAT sync: configurable via UI or env vars.
"""
from alembic import op
import sqlalchemy as sa

revision = "021_add_git_sync_repo_config"
down_revision = "020_add_run_config_to_downstream_triggers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orchestrator_settings",
        sa.Column("git_sync_repo_url", sa.String(), nullable=True),
    )
    op.add_column(
        "orchestrator_settings",
        sa.Column("git_sync_token_encrypted", sa.String(), nullable=True),
    )
    op.add_column(
        "orchestrator_settings",
        sa.Column("git_sync_branch", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orchestrator_settings", "git_sync_branch")
    op.drop_column("orchestrator_settings", "git_sync_token_encrypted")
    op.drop_column("orchestrator_settings", "git_sync_repo_url")
