"""Add git_sha, git_branch, git_commit_message to pipeline_runs

Revision ID: 027_add_git_sha
Revises: 026_add_notification_api
Create Date: 2025-02-27

Stores Git HEAD (SHA, branch, commit message) at run start for reproducibility.
"""
from alembic import op
import sqlalchemy as sa

revision = "027_add_git_sha"
down_revision = "026_add_notification_api"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pipeline_runs", sa.Column("git_sha", sa.String(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("git_branch", sa.String(), nullable=True))
    op.add_column("pipeline_runs", sa.Column("git_commit_message", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("pipeline_runs", "git_commit_message")
    op.drop_column("pipeline_runs", "git_branch")
    op.drop_column("pipeline_runs", "git_sha")
