"""Add revocable sessions and database-backed abuse counters.

Revision ID: c19a6e72d440
Revises: b6a4e9d2c813
"""
from alembic import op
import sqlalchemy as sa

revision = "c19a6e72d440"
down_revision = "b6a4e9d2c813"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("password_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("last_seen_at", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("idle_seconds", sa.Integer(), nullable=False),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_table(
        "rate_limit_buckets",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
    )
    op.create_index("ix_rate_limit_buckets_expires_at", "rate_limit_buckets", ["expires_at"])


def downgrade():
    op.drop_table("rate_limit_buckets")
    op.drop_table("auth_sessions")
