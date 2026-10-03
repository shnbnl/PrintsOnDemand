"""Add professor accounts and student delivery consent.

Revision ID: 8d41c20e7f09
Revises: 3f1a9d7c2b61
"""

from alembic import op
import sqlalchemy as sa


revision = "8d41c20e7f09"
down_revision = "3f1a9d7c2b61"
branch_labels = None
depends_on = None


def _sqlite_foreign_keys(enabled: bool):
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.get_context().autocommit_block():
            bind.exec_driver_sql(f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}")


def upgrade():
    op.add_column("professors", sa.Column(
        "accepts_student_deliveries", sa.Boolean(), nullable=False, server_default=sa.false()
    ))
    op.add_column("orders", sa.Column("professor_recipient_type", sa.String(20), nullable=True))
    op.execute("UPDATE orders SET professor_recipient_type = 'STUDENT_SELECTED' WHERE destination = 'PROFESSOR'")
    op.execute("UPDATE shop_services SET enabled = FALSE WHERE service_type = 'DIRECT_TO_PROFESSOR' AND shop_id IN (SELECT id FROM printing_shops WHERE name <> 'Blue and Silver Bookstore')")

    _sqlite_foreign_keys(False)
    try:
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(sa.Column("professor_id", sa.Integer(), nullable=True))
            batch_op.create_unique_constraint("uq_users_professor_id", ["professor_id"])
            batch_op.create_foreign_key("fk_users_professor_id", "professors", ["professor_id"], ["id"], ondelete="RESTRICT")
            batch_op.drop_constraint("user_role", type_="check")
            batch_op.create_check_constraint(
                "user_role", "role IN ('STUDENT', 'PROFESSOR', 'SHOP_STAFF', 'ADMIN')"
            )
    finally:
        _sqlite_foreign_keys(True)


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM users WHERE role = 'PROFESSOR' LIMIT 1")).first():
        raise RuntimeError("Remove professor accounts before downgrading this migration.")
    _sqlite_foreign_keys(False)
    try:
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_constraint("fk_users_professor_id", type_="foreignkey")
            batch_op.drop_constraint("uq_users_professor_id", type_="unique")
            batch_op.drop_column("professor_id")
            batch_op.drop_constraint("user_role", type_="check")
            batch_op.create_check_constraint("user_role", "role IN ('STUDENT', 'SHOP_STAFF', 'ADMIN')")
    finally:
        _sqlite_foreign_keys(True)
    op.drop_column("orders", "professor_recipient_type")
    op.drop_column("professors", "accepts_student_deliveries")
