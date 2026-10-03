"""Preserve precise shop coordinates as decimal text.

Revision ID: 3f1a9d7c2b61
Revises: a7e918c4b250
"""

from alembic import op
import sqlalchemy as sa


revision = "3f1a9d7c2b61"
down_revision = "a7e918c4b250"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"
    if sqlite:
        # Batch alteration rebuilds the parent table. Turn off SQLite cascades
        # for that table replacement so related shop services/prices survive.
        with op.get_context().autocommit_block():
            bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    try:
        with op.batch_alter_table("printing_shops") as batch_op:
            batch_op.drop_constraint("shop_latitude_range", type_="check")
            batch_op.drop_constraint("shop_longitude_range", type_="check")
            batch_op.alter_column(
                "latitude",
                existing_type=sa.Numeric(9, 6),
                type_=sa.String(32),
                existing_nullable=True,
            )
            batch_op.create_check_constraint(
                "shop_latitude_range", "CAST(latitude AS NUMERIC) BETWEEN -90 AND 90"
            )
            batch_op.create_check_constraint(
                "shop_longitude_range", "CAST(longitude AS NUMERIC) BETWEEN -180 AND 180"
            )
            batch_op.alter_column(
                "longitude",
                existing_type=sa.Numeric(9, 6),
                type_=sa.String(32),
                existing_nullable=True,
            )
    finally:
        if sqlite:
            with op.get_context().autocommit_block():
                bind.exec_driver_sql("PRAGMA foreign_keys=ON")


def downgrade():
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"
    if sqlite:
        with op.get_context().autocommit_block():
            bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    try:
        with op.batch_alter_table("printing_shops") as batch_op:
            batch_op.drop_constraint("shop_latitude_range", type_="check")
            batch_op.drop_constraint("shop_longitude_range", type_="check")
            batch_op.alter_column(
                "latitude",
                existing_type=sa.String(32),
                type_=sa.Numeric(9, 6),
                existing_nullable=True,
            )
            batch_op.create_check_constraint("shop_latitude_range", "latitude BETWEEN -90 AND 90")
            batch_op.create_check_constraint("shop_longitude_range", "longitude BETWEEN -180 AND 180")
            batch_op.alter_column(
                "longitude",
                existing_type=sa.String(32),
                type_=sa.Numeric(9, 6),
                existing_nullable=True,
            )
    finally:
        if sqlite:
            with op.get_context().autocommit_block():
                bind.exec_driver_sql("PRAGMA foreign_keys=ON")
