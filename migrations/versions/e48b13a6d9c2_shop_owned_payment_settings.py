"""Store independent payment settings and QR images on each printing shop.

Revision ID: e48b13a6d9c2
Revises: 6d9f3a8c12e4
"""

from alembic import op
import sqlalchemy as sa
from flask import current_app

from app.services.payment_qr import development_qr


revision = "e48b13a6d9c2"
down_revision = "6d9f3a8c12e4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("printing_shops", sa.Column("cash_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("printing_shops", sa.Column("online_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("printing_shops", sa.Column("online_account_name", sa.String(120), nullable=False, server_default=""))
    op.add_column("printing_shops", sa.Column("online_account_reference", sa.String(255), nullable=False, server_default=""))
    op.add_column("printing_shops", sa.Column("online_instructions", sa.Text(), nullable=False, server_default=""))
    op.add_column("printing_shops", sa.Column("payment_qr_data", sa.LargeBinary(), nullable=True))
    op.add_column("printing_shops", sa.Column("payment_qr_mime", sa.String(32), nullable=True))
    op.add_column("printing_shops", sa.Column("payment_qr_digest", sa.String(64), nullable=True))

    connection = op.get_bind()
    legacy = connection.execute(sa.text(
        "SELECT online_enabled, online_account_name, online_destination, online_instructions "
        "FROM payment_settings WHERE id = 1"
    )).mappings().first()
    initial = dict(legacy) if legacy else {
        "online_enabled": bool(current_app.config.get("ONLINE_PAYMENT_ENABLED")),
        "online_account_name": current_app.config.get("ONLINE_PAYMENT_ACCOUNT_NAME", ""),
        "online_destination": current_app.config.get("ONLINE_PAYMENT_DESTINATION", ""),
        "online_instructions": current_app.config.get("ONLINE_PAYMENT_INSTRUCTIONS", ""),
    }
    shops = connection.execute(sa.text("SELECT id, name FROM printing_shops")).mappings().all()
    for shop in shops:
        qr_data, qr_mime, qr_digest = development_qr(shop["name"])
        values = {
            "id": shop["id"], "qr_data": qr_data, "qr_mime": qr_mime, "qr_digest": qr_digest,
            "online_enabled": bool(initial["online_enabled"]),
            "account_name": initial["online_account_name"],
            "account_reference": initial["online_destination"],
            "instructions": initial["online_instructions"],
        }
        connection.execute(sa.text(
            "UPDATE printing_shops SET payment_qr_data=:qr_data, payment_qr_mime=:qr_mime, "
            "payment_qr_digest=:qr_digest, online_enabled=:online_enabled, "
            "online_account_name=:account_name, online_account_reference=:account_reference, "
            "online_instructions=:instructions WHERE id=:id"
        ), values)


def downgrade():
    for name in (
            "payment_qr_digest", "payment_qr_mime", "payment_qr_data", "online_instructions",
            "online_account_reference", "online_account_name", "online_enabled", "cash_enabled",
    ):
        op.drop_column("printing_shops", name)
