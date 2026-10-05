"""Mark checkout-only uploads for safe expiry without touching legacy files.

Revision ID: 6d9f3a8c12e4
Revises: f4a93d81c2e0
"""

from alembic import op
import sqlalchemy as sa


revision = "6d9f3a8c12e4"
down_revision = "f4a93d81c2e0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("uploaded_files", sa.Column("checkout_staged_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_uploaded_files_checkout_staged_at", "uploaded_files", ["checkout_staged_at"])


def downgrade():
    op.drop_index("ix_uploaded_files_checkout_staged_at", table_name="uploaded_files")
    op.drop_column("uploaded_files", "checkout_staged_at")
