"""Store self-reported professor department and pending delivery preference.

Revision ID: c2d95e7a104b
Revises: 91d2e4b6a7c8
"""

from alembic import op
import sqlalchemy as sa


revision = "c2d95e7a104b"
down_revision = "91d2e4b6a7c8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("professor_department", sa.String(120), nullable=True))
    op.add_column("users", sa.Column(
        "student_delivery_preference", sa.Boolean(), nullable=False,
        server_default=sa.false(),
    ))


def downgrade():
    op.drop_column("users", "student_delivery_preference")
    op.drop_column("users", "professor_department")
