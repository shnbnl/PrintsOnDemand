"""Stage 16 migration keeps older order rows and reverses safely."""

from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text

from app.extensions import db
from test_stage6_migration import migration_app


def test_fresh_fulfillment_schema_and_downgrade(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "stage16-fresh.db", monkeypatch)
    with app.app_context():
        upgrade()
        columns = {column["name"]: column for column in inspect(db.engine).get_columns("orders")}
        assert {"pickup_date", "pickup_slot", "delivery_recipient_name",
                "delivery_recipient_phone", "delivery_address", "delivery_date",
                "delivery_slot", "delivery_fee"} <= columns.keys()
        assert not columns["delivery_fee"]["nullable"]
        downgrade(revision="17e6c1fa14a0")
        columns = {column["name"] for column in inspect(db.engine).get_columns("orders")}
        assert "pickup_date" not in columns and "delivery_fee" not in columns
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.remove()
        db.engine.dispose()


def test_existing_order_total_and_destination_survive_upgrade(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "stage16-existing.db", monkeypatch)
    with app.app_context():
        upgrade(revision="17e6c1fa14a0")
        now = "2026-10-03 00:00:00"
        db.session.execute(text("""
            INSERT INTO users (id, name, email, password_hash, role, is_active, created_at, updated_at)
            VALUES (1, 'Existing Student', 'old16@example.edu', '!', 'STUDENT', 1, :now, :now)
        """), {"now": now})
        db.session.execute(text("""
            INSERT INTO printing_shops (id, name, description, address, opening_time,
                closing_time, is_active, is_demo, created_at, updated_at)
            VALUES (1, 'Existing Shop', '', 'Campus', '09:00:00', '17:00:00', 1, 0, :now, :now)
        """), {"now": now})
        db.session.execute(text("""
            INSERT INTO orders (id, user_id, shop_id, order_reference, shop_name,
                status, subtotal, rush_fee, fees_total, total, currency, created_at, updated_at)
            VALUES (1, 1, 1, 'POD-2026-OLD16', 'Existing Shop', 'READY',
                11.25, 5.50, 5.50, 16.75, 'PHP', :now, :now)
        """), {"now": now})
        db.session.commit()
        upgrade()
        row = db.session.execute(text("""
            SELECT destination, pickup_date, delivery_date, delivery_fee, subtotal, rush_fee,
                   fees_total, total, status FROM orders WHERE id = 1
        """)).one()
        assert row.destination is row.pickup_date is row.delivery_date is None
        assert float(row.delivery_fee) == 0
        assert (float(row.subtotal), float(row.rush_fee), float(row.fees_total),
                float(row.total), row.status) == (11.25, 5.5, 5.5, 16.75, "READY")
        downgrade(revision="17e6c1fa14a0")
        assert db.session.execute(text(
            "SELECT total FROM orders WHERE id = 1"
        )).scalar_one() == 16.75
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.remove()
        db.engine.dispose()
