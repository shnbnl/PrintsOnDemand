"""Add optional admin override for public manual payment instructions.

Revision ID: b37d5be5c2a1
Revises: 92c4f0a1d9e7
"""

from alembic import op
import sqlalchemy as sa


revision = "b37d5be5c2a1"
down_revision = "92c4f0a1d9e7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payment_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("online_enabled", sa.Boolean(), nullable=False),
        sa.Column("online_instructions", sa.Text(), nullable=False),
        sa.Column("online_account_name", sa.String(length=120), nullable=False),
        sa.Column("online_destination", sa.String(length=255), nullable=False),
        sa.Column("onsite_instructions", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="payment_settings_singleton"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("payment_settings")
