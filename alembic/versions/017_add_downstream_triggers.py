"""Add downstream_triggers table for pipeline chaining

Revision ID: 017_add_downstream_triggers
Revises: 016_add_scheduled_job_start_end_source
Create Date: 2025-02-05

Pipeline chaining: when pipeline A finishes, start pipeline B (on_success/on_failure).
"""
from alembic import op
import sqlalchemy as sa

revision = "017_add_downstream_triggers"
down_revision = "016_add_scheduled_job_start_end_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "downstream_triggers",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("upstream_pipeline", sa.String(), nullable=False),
        sa.Column("downstream_pipeline", sa.String(), nullable=False),
        sa.Column("on_success", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("on_failure", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_downstream_triggers_upstream_pipeline",
        "downstream_triggers",
        ["upstream_pipeline"],
        unique=False,
    )
    op.create_index(
        "ix_downstream_triggers_downstream_pipeline",
        "downstream_triggers",
        ["downstream_pipeline"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_downstream_triggers_downstream_pipeline", "downstream_triggers")
    op.drop_index("ix_downstream_triggers_upstream_pipeline", "downstream_triggers")
    op.drop_table("downstream_triggers")
