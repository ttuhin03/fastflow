"""Add ip_address to audit_log

Revision ID: 038_add_audit_ip_address
Revises: 037_add_s3_test_on_save
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa

revision = "038_add_audit_ip_address"
down_revision = "037_add_s3_test_on_save"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_log",
        sa.Column("ip_address", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("audit_log", "ip_address")
