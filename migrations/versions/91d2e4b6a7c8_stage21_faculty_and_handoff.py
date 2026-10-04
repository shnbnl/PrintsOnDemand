"""Add controlled Faculty snapshot and physical professor handoff state.

Revision ID: 91d2e4b6a7c8
Revises: 8d41c20e7f09
"""

from alembic import op
import sqlalchemy as sa


revision = "91d2e4b6a7c8"
down_revision = "8d41c20e7f09"
branch_labels = None
depends_on = None

FACULTY_CHECK = "faculty IS NULL OR faculty IN ('MITL', 'CAS', 'ETYCB', 'CCIS', 'CHS', 'GE', 'IECELL', 'SHS')"
ORDER_FACULTY_CHECK = "professor_faculty IS NULL OR professor_faculty IN ('MITL', 'CAS', 'ETYCB', 'CCIS', 'CHS', 'GE', 'IECELL', 'SHS')"


def _foreign_keys(enabled):
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.get_context().autocommit_block():
            bind.exec_driver_sql(f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}")


def upgrade():
    _foreign_keys(False)
    try:
        with op.batch_alter_table("professors") as batch:
            batch.add_column(sa.Column("faculty", sa.String(16), nullable=True))
            batch.create_check_constraint("professor_faculty_valid", FACULTY_CHECK)
        # These fictional seed identities have known Faculty values. Do not
        # guess a Faculty for any other pre-existing professor profile.
        op.execute("UPDATE professors SET faculty = 'MITL' WHERE faculty IS NULL AND email IN ('maria.santos@example.edu', 'ana.reyes@example.edu')")
        op.execute("UPDATE professors SET faculty = 'CCIS' WHERE faculty IS NULL AND email = 'juan.delacruz@example.edu'")
        op.execute("UPDATE professors SET faculty = 'CAS' WHERE faculty IS NULL AND email = 'liza.navarro@example.edu'")
        with op.batch_alter_table("orders") as batch:
            batch.add_column(sa.Column("professor_faculty", sa.String(16), nullable=True))
            batch.add_column(sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))
            batch.create_check_constraint("order_professor_faculty_valid", ORDER_FACULTY_CHECK)
            batch.drop_constraint("order_status", type_="check")
            batch.create_check_constraint(
                "order_status", "status IN ('PENDING_PAYMENT', 'PROCESSING', 'READY', 'DELIVERED', 'COMPLETED')"
            )
    finally:
        _foreign_keys(True)


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM orders WHERE status = 'DELIVERED' LIMIT 1")).first():
        raise RuntimeError("Complete delivered orders before downgrading Stage 21.")
    _foreign_keys(False)
    try:
        with op.batch_alter_table("orders") as batch:
            batch.drop_constraint("order_professor_faculty_valid", type_="check")
            batch.drop_constraint("order_status", type_="check")
            batch.create_check_constraint(
                "order_status", "status IN ('PENDING_PAYMENT', 'PROCESSING', 'READY', 'COMPLETED')"
            )
            batch.drop_column("delivered_at")
            batch.drop_column("professor_faculty")
        with op.batch_alter_table("professors") as batch:
            batch.drop_constraint("professor_faculty_valid", type_="check")
            batch.drop_column("faculty")
    finally:
        _foreign_keys(True)
