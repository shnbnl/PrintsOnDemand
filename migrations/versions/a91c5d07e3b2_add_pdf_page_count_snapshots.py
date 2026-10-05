"""Store PDF page counts and printed-page order snapshots."""

from alembic import op
import sqlalchemy as sa


revision = "a91c5d07e3b2"
down_revision = "e48b13a6d9c2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("uploaded_files", sa.Column("pdf_page_count", sa.Integer(), nullable=True))
    op.add_column("order_items", sa.Column("pdf_page_count", sa.Integer(), nullable=True))
    op.add_column("order_items", sa.Column("total_printed_pages", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("order_items", "total_printed_pages")
    op.drop_column("order_items", "pdf_page_count")
    op.drop_column("uploaded_files", "pdf_page_count")
