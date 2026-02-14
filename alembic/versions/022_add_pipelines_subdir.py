"""Add pipelines_subdir to orchestrator_settings

Revision ID: 022_add_pipelines_subdir
Revises: 021_add_git_sync_repo_config
Create Date: 2025-02-14

Wenn die Pipelines im Repo in einem Unterordner liegen (z. B. pipelines/),
kann dieser hier oder per PIPELINES_SUBDIR gesetzt werden.
"""
from alembic import op
import sqlalchemy as sa

revision = "022_add_pipelines_subdir"
down_revision = "021_add_git_sync_repo_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orchestrator_settings",
        sa.Column("pipelines_subdir", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orchestrator_settings", "pipelines_subdir")
