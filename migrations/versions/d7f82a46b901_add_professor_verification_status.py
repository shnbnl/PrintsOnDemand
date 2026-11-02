"""Track Blue and Silver verification of Professor accounts.

Revision ID: d7f82a46b901
Revises: c2d95e7a104b
"""

from alembic import op
import sqlalchemy as sa


revision = "d7f82a46b901"
down_revision = "c2d95e7a104b"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column(
        "professor_verification_status", sa.Enum(
            "PENDING", "VERIFIED", "REJECTED",
            name="professor_verification_status", native_enum=False,
        ), nullable=False,
        server_default="PENDING",
    ))
    # Preserve existing trusted, active/approved links. Unlinked or unapproved
    # Professor accounts still require explicit Blue and Silver verification.
    op.execute("""
        UPDATE users SET professor_verification_status = 'VERIFIED'
        WHERE role = 'PROFESSOR' AND professor_id IN (
            SELECT id FROM professors WHERE is_active = 1 AND direct_send_approved = 1
        )
    """)


def downgrade():
    op.drop_column("users", "professor_verification_status")
