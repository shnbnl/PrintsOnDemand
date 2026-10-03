"""Add requested pickup and delivery snapshots to orders.

Revision ID: 6c2a09d4f518
Revises: 17e6c1fa14a0
"""

from alembic import op
import sqlalchemy as sa


revision = "6c2a09d4f518"
down_revision = "17e6c1fa14a0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("orders", sa.Column("pickup_date", sa.Date(), nullable=True))
    op.add_column("orders", sa.Column("pickup_slot", sa.String(32), nullable=True))
    op.add_column("orders", sa.Column("delivery_recipient_name", sa.String(120), nullable=True))
    op.add_column("orders", sa.Column("delivery_recipient_phone", sa.String(32), nullable=True))
    op.add_column("orders", sa.Column("delivery_address", sa.String(500), nullable=True))
    op.add_column("orders", sa.Column("delivery_date", sa.Date(), nullable=True))
    op.add_column("orders", sa.Column("delivery_slot", sa.String(32), nullable=True))
    op.add_column("orders", sa.Column("delivery_fee", sa.Numeric(14, 2),
                                      sa.CheckConstraint("delivery_fee >= 0", name="order_delivery_fee_nonnegative"),
                                      nullable=False, server_default="0.00"))


def downgrade():
    # SQLite rebuilds orders when dropping columns. Preserve cascading child rows.
    sqlite = op.get_bind().dialect.name == "sqlite"
    if sqlite:
        op.execute("CREATE TEMP TABLE stage16_order_items_backup AS SELECT * FROM order_items")
        op.execute("CREATE TEMP TABLE stage16_payments_backup AS SELECT * FROM payments")
        op.execute("DELETE FROM payments")
    with op.batch_alter_table("orders") as batch:
        batch.drop_constraint("order_delivery_fee_nonnegative", type_="check")
        for column in ("delivery_fee", "delivery_slot", "delivery_date", "delivery_address",
                       "delivery_recipient_phone", "delivery_recipient_name", "pickup_slot", "pickup_date"):
            batch.drop_column(column)
    if sqlite:
        op.execute("INSERT INTO order_items SELECT * FROM stage16_order_items_backup")
        op.execute("INSERT INTO payments SELECT * FROM stage16_payments_backup")
        op.execute("DROP TABLE stage16_order_items_backup")
        op.execute("DROP TABLE stage16_payments_backup")
