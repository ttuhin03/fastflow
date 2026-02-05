"""Add start_date, end_date, source to scheduled_jobs

Revision ID: 016_add_scheduled_job_start_end_source
Revises: 015_add_orchestrator_settings
Create Date: 2025-02-05

Optional time window (start_date, end_date) for schedules and source (api | pipeline_json).
"""
from alembic import op
import sqlalchemy as sa

revision = "016_add_scheduled_job_start_end_source"
down_revision = "015_add_orchestrator_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scheduled_jobs",
        sa.Column("start_date", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "scheduled_jobs",
        sa.Column("end_date", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "scheduled_jobs",
        sa.Column("source", sa.String(), nullable=False, server_default="api"),
    )


def downgrade() -> None:
    op.drop_column("scheduled_jobs", "source")
    op.drop_column("scheduled_jobs", "end_date")
    op.drop_column("scheduled_jobs", "start_date")
