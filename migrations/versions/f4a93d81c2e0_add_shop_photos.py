"""Store bounded shop photos for directory and map markers.

Revision ID: f4a93d81c2e0
Revises: d7f82a46b901
"""

from alembic import op
import sqlalchemy as sa


revision = "f4a93d81c2e0"
down_revision = "d7f82a46b901"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("printing_shops", sa.Column("photo_data", sa.LargeBinary(), nullable=True))
    op.add_column("printing_shops", sa.Column("photo_mime", sa.String(32), nullable=True))
    op.add_column("printing_shops", sa.Column("photo_digest", sa.String(64), nullable=True))
    # Replace only the original seeded placeholder; preserve customized addresses.
    op.execute("""
        UPDATE printing_shops
        SET address = 'Near Mapúa Malayan Colleges Laguna'
        WHERE is_demo = TRUE
          AND address = 'Demo location near Mapúa Malayan Colleges Laguna'
          AND name IN (
              'Blue and Silver Bookstore', 'CHALECOSPOT',
              'Iced Design and Prints', 'Pixels Print and Press'
          )
    """)


def downgrade():
    op.drop_column("printing_shops", "photo_digest")
    op.drop_column("printing_shops", "photo_mime")
    op.drop_column("printing_shops", "photo_data")
