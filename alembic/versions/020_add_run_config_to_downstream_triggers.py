"""Add run_config_id to downstream_triggers

Revision ID: 020_add_run_config_to_downstream_triggers
Revises: 019_add_run_config_id
Create Date: 2025-02-07

Optional run_config_id to select which schedule of the downstream pipeline to use.
"""
from alembic import op
import sqlalchemy as sa

revision = "020_add_run_config_to_downstream_triggers"
down_revision = "019_add_run_config_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "downstream_triggers",
        sa.Column("run_config_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("downstream_triggers", "run_config_id")
