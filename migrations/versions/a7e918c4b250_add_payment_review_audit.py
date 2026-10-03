"""Keep online submission and manual review audit details.

Revision ID: a7e918c4b250
Revises: 6c2a09d4f518
"""

from alembic import op
import sqlalchemy as sa


revision = "a7e918c4b250"
down_revision = "6c2a09d4f518"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("payments") as batch:
        batch.add_column(sa.Column("submitted_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("reviewed_by_id", sa.Integer()))
        batch.add_column(sa.Column("rejection_reason", sa.String(500)))
        batch.create_foreign_key("fk_payments_reviewed_by_id", "users", ["reviewed_by_id"], ["id"], ondelete="RESTRICT")
    # Pre-existing submitted references used updated_at as their submission time.
    op.execute("UPDATE payments SET submitted_at = updated_at WHERE payment_status = 'SUBMITTED'")


def downgrade():
    with op.batch_alter_table("payments") as batch:
        batch.drop_constraint("fk_payments_reviewed_by_id", type_="foreignkey")
        batch.drop_column("rejection_reason")
        batch.drop_column("reviewed_by_id")
        batch.drop_column("reviewed_at")
        batch.drop_column("submitted_at")
