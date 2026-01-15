"""Add webhook_runs to Pipeline and triggered_by to PipelineRun

Revision ID: 002_add_webhook_fields
Revises: 001_add_is_parameter
Create Date: 2024-01-02 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002_add_webhook_fields'
down_revision = '001_add_is_parameter'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add webhook_runs column to pipelines table
    # SQLite requires batch mode for adding columns
    with op.batch_alter_table('pipelines', schema=None) as batch_op:
        batch_op.add_column(sa.Column('webhook_runs', sa.Integer(), nullable=False, server_default='0'))
    
    # Add triggered_by column to pipeline_runs table
    with op.batch_alter_table('pipeline_runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('triggered_by', sa.String(), nullable=False, server_default='manual'))


def downgrade() -> None:
    # Remove triggered_by column from pipeline_runs table
    with op.batch_alter_table('pipeline_runs', schema=None) as batch_op:
        batch_op.drop_column('triggered_by')
    
    # Remove webhook_runs column from pipelines table
    with op.batch_alter_table('pipelines', schema=None) as batch_op:
        batch_op.drop_column('webhook_runs')
