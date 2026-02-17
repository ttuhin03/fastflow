"""Add pipeline_daily_stats table for persistent calendar counts

Revision ID: 025_add_pipeline_daily_stats
Revises: 024_dependency_audit_enabled_default_true
Create Date: 2025-02-17

Persistent daily run counts per pipeline so calendar heatmap survives log/run cleanup.
"""
from alembic import op
import sqlalchemy as sa

revision = "025_add_pipeline_daily_stats"
down_revision = "024_dependency_audit_enabled_default_true"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_daily_stats",
        sa.Column("pipeline_name", sa.String(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("total_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("successful_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("pipeline_name", "day"),
        sa.ForeignKeyConstraint(["pipeline_name"], ["pipelines.pipeline_name"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_pipeline_daily_stats_pipeline_name_date",
        "pipeline_daily_stats",
        ["pipeline_name", "day"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_pipeline_daily_stats_pipeline_name_date", table_name="pipeline_daily_stats")
    op.drop_table("pipeline_daily_stats")
