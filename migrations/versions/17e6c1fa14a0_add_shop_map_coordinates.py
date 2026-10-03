"""Add optional map coordinates to printing shops.

Revision ID: 17e6c1fa14a0
Revises: b37d5be5c2a1
"""

from alembic import op
import sqlalchemy as sa


revision = "17e6c1fa14a0"
down_revision = "b37d5be5c2a1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("printing_shops", sa.Column(
        "latitude", sa.Numeric(9, 6),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90", name="shop_latitude_range"),
        nullable=True,
    ))
    op.add_column("printing_shops", sa.Column(
        "longitude", sa.Numeric(9, 6),
        sa.CheckConstraint("longitude BETWEEN -180 AND 180", name="shop_longitude_range"),
        nullable=True,
    ))


def downgrade():
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"
    if sqlite:
        with op.get_context().autocommit_block():
            bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    try:
        with op.batch_alter_table("printing_shops") as batch_op:
            batch_op.drop_constraint("shop_longitude_range", type_="check")
            batch_op.drop_constraint("shop_latitude_range", type_="check")
            batch_op.drop_column("longitude")
            batch_op.drop_column("latitude")
    finally:
        if sqlite:
            with op.get_context().autocommit_block():
                bind.exec_driver_sql("PRAGMA foreign_keys=ON")
