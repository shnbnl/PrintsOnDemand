"""Add shared counters for sensitive request throttling.

Revision ID: b842c0e16a7f
Revises: a91c5d07e3b2
"""

from alembic import op
import sqlalchemy as sa


revision = "b842c0e16a7f"
down_revision = "a91c5d07e3b2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "rate_limit_buckets",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("window_start", sa.BigInteger(), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
    )
    op.create_index("ix_rate_limit_buckets_window_start", "rate_limit_buckets", ["window_start"])


def downgrade():
    op.drop_index("ix_rate_limit_buckets_window_start", table_name="rate_limit_buckets")
    op.drop_table("rate_limit_buckets")
