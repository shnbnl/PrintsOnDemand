"""Add shop-processing states and event timestamps.

Revision ID: 92c4f0a1d9e7
Revises: 6fb08dfd51de
"""

from alembic import op
import sqlalchemy as sa


revision = "92c4f0a1d9e7"
down_revision = "6fb08dfd51de"
branch_labels = None
depends_on = None


def _backup_dependents():
    if op.get_bind().dialect.name != "sqlite":
        return False
    # SQLite recreates orders for its enum CHECK change. Empty dependent tables
    # first so its DROP cannot cascade items or hit payments' RESTRICT FK.
    op.execute("CREATE TEMP TABLE stage9_items_backup AS SELECT * FROM order_items")
    op.execute("CREATE TEMP TABLE stage9_payments_backup AS SELECT * FROM payments")
    op.execute("DELETE FROM payments")
    op.execute("DELETE FROM order_items")
    return True


def _restore_dependents(backed_up):
    if backed_up:
        op.execute("INSERT INTO order_items SELECT * FROM stage9_items_backup")
        op.execute("INSERT INTO payments SELECT * FROM stage9_payments_backup")
        op.execute("DROP TABLE stage9_items_backup")
        op.execute("DROP TABLE stage9_payments_backup")


def _change_status_constraint(allowed, *, drop_timestamps=False):
    with op.batch_alter_table("orders", recreate="always" if op.get_bind().dialect.name == "sqlite" else "auto") as batch:
        batch.drop_constraint("order_status", type_="check")
        values = ", ".join(f"'{value}'" for value in allowed)
        batch.create_check_constraint("order_status", f"status IN ({values})")
        if drop_timestamps:
            for name in ("completed_at", "ready_at", "processing_started_at"):
                batch.drop_column(name)


def upgrade():
    for name in ("processing_started_at", "ready_at", "completed_at"):
        op.add_column("orders", sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    backed_up = _backup_dependents()
    _change_status_constraint(("PENDING_PAYMENT", "PROCESSING", "READY", "COMPLETED"))
    _restore_dependents(backed_up)


def downgrade():
    if op.get_bind().execute(sa.text(
        "SELECT count(*) FROM orders WHERE status <> 'PENDING_PAYMENT'"
    )).scalar_one():
        raise RuntimeError("Cannot downgrade while processed orders exist.")
    backed_up = _backup_dependents()
    _change_status_constraint(("PENDING_PAYMENT",), drop_timestamps=True)
    _restore_dependents(backed_up)
