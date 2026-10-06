"""Add expiring password reset grants and durable request throttling.

Revision ID: b68a5e2c4f19
Revises: a91c5d07e3b2
"""

from alembic import op
import sqlalchemy as sa


revision = "b68a5e2c4f19"
down_revision = "a91c5d07e3b2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "password_reset_grants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_password_reset_grants_user_id", "password_reset_grants", ["user_id"])
    op.create_table(
        "password_reset_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("throttle_key", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_password_reset_attempts_throttle_key", "password_reset_attempts", ["throttle_key"])


def downgrade():
    op.drop_index("ix_password_reset_attempts_throttle_key", table_name="password_reset_attempts")
    op.drop_table("password_reset_attempts")
    op.drop_index("ix_password_reset_grants_user_id", table_name="password_reset_grants")
    op.drop_table("password_reset_grants")
