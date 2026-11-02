"""Add shop breaks and staff-managed professor recipients.

Revision ID: c42a1d87e609
Revises: ab14d7e93c20
"""
from alembic import op
import sqlalchemy as sa

revision = "c42a1d87e609"
down_revision = "ab14d7e93c20"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("printing_shops", sa.Column("is_on_break", sa.Boolean(), nullable=False,
                                            server_default=sa.false()))
    op.add_column("professors", sa.Column("is_staff_managed", sa.Boolean(), nullable=False,
                                        server_default=sa.false()))


def downgrade():
    # Native column removal preserves tables referenced by existing orders.
    op.drop_column("professors", "is_staff_managed")
    op.drop_column("printing_shops", "is_on_break")
