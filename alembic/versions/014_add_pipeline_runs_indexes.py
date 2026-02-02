"""Add indexes on pipeline_runs for performance

Revision ID: 014_add_pipeline_runs_indexes
Revises: 013_add_dependency_audit_settings
Create Date: 2025-02-02

Indexes for common query patterns:
- started_at: ORDER BY in runs listing
- (pipeline_name, started_at): filtered runs by pipeline
- status: filter by RUNNING, SUCCESS, etc.
"""
from alembic import op

revision = "014_add_pipeline_runs_indexes"
down_revision = "013_add_dependency_audit_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # postgresql_ops nur für PostgreSQL; SQLite ignoriert es
    op.create_index(
        "ix_pipeline_runs_started_at",
        "pipeline_runs",
        ["started_at"],
        postgresql_ops={"started_at": "DESC"},
    )
    op.create_index(
        "ix_pipeline_runs_pipeline_name_started_at",
        "pipeline_runs",
        ["pipeline_name", "started_at"],
        postgresql_ops={"started_at": "DESC"},
    )
    op.create_index("ix_pipeline_runs_status", "pipeline_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_pipeline_runs_status", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_pipeline_name_started_at", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_started_at", table_name="pipeline_runs")
