"""Add run_config_id to scheduled_jobs and pipeline_runs

Revision ID: 019_add_run_config_id
Revises: 018_add_custom_oauth_id
Create Date: 2025-02-06

Optional run_config_id for multiple run configs per pipeline (schedules in pipeline.json).
"""
from alembic import op
import sqlalchemy as sa

revision = "019_add_run_config_id"
down_revision = "018_add_custom_oauth_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scheduled_jobs",
        sa.Column("run_config_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_scheduled_jobs_run_config_id",
        "scheduled_jobs",
        ["run_config_id"],
        unique=False,
    )
    op.add_column(
        "pipeline_runs",
        sa.Column("run_config_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_pipeline_runs_run_config_id",
        "pipeline_runs",
        ["run_config_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_pipeline_runs_run_config_id", table_name="pipeline_runs")
    op.drop_column("pipeline_runs", "run_config_id")
    op.drop_index("ix_scheduled_jobs_run_config_id", table_name="scheduled_jobs")
    op.drop_column("scheduled_jobs", "run_config_id")
