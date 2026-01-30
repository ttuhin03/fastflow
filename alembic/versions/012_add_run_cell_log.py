"""Add run_cell_logs table for notebook cell-level logs

Revision ID: 012_add_run_cell_log
Revises: 011_add_system_settings
Create Date: 2025-01-30

"""
from alembic import op
import sqlalchemy as sa

revision = "012_add_run_cell_log"
down_revision = "011_add_system_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_cell_logs",
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("cell_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="RUNNING"),
        sa.Column("stdout", sa.Text(), nullable=False, server_default=""),
        sa.Column("stderr", sa.Text(), nullable=False, server_default=""),
        sa.Column("outputs", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["pipeline_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "cell_index"),
    )


def downgrade() -> None:
    op.drop_table("run_cell_logs")
