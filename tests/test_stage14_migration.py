"""Map-coordinate migration supports fresh and populated databases."""

from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text

from app.extensions import db
from tests.test_stage6_migration import migration_app


def test_fresh_database_has_nullable_shop_coordinates(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "map-fresh.db", monkeypatch)
    with app.app_context():
        upgrade()
        columns = {column["name"]: column for column in inspect(db.engine).get_columns("printing_shops")}
        assert columns["latitude"]["nullable"]
        assert columns["longitude"]["nullable"]
        assert {"latitude", "longitude"} <= columns.keys()
        db.session.remove()
        db.engine.dispose()


def test_existing_shop_and_order_survive_coordinate_migration(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "map-existing.db", monkeypatch)
    with app.app_context():
        upgrade(revision="b37d5be5c2a1")
        now = "2026-10-03 00:00:00"
        db.session.execute(text("""
            INSERT INTO users (id, name, email, password_hash, role, is_active, created_at, updated_at)
            VALUES (1, 'Existing Student', 'existing@example.edu', '!', 'STUDENT', 1, :now, :now)
        """), {"now": now})
        db.session.execute(text("""
            INSERT INTO printing_shops
                (id, name, description, address, opening_time, closing_time,
                 is_active, is_demo, created_at, updated_at)
            VALUES (1, 'Existing Shop', '', 'Campus', '09:00:00', '17:00:00', 1, 0, :now, :now)
        """), {"now": now})
        db.session.execute(text("""
            INSERT INTO orders
                (id, user_id, shop_id, order_reference, shop_name, status,
                 subtotal, rush_fee, fees_total, total, currency, created_at, updated_at)
            VALUES (1, 1, 1, 'POD-2026-EXISTING001', 'Existing Shop',
                    'PENDING_PAYMENT', 6.75, 0, 0, 6.75, 'PHP', :now, :now)
        """), {"now": now})
        db.session.commit()

        upgrade()
        shop = db.session.execute(text(
            "SELECT name, latitude, longitude FROM printing_shops WHERE id = 1"
        )).one()
        assert shop == ("Existing Shop", None, None)
        order = db.session.execute(text(
            "SELECT order_reference, total FROM orders WHERE id = 1"
        )).one()
        assert order.order_reference == "POD-2026-EXISTING001"
        assert float(order.total) == 6.75
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.remove()
        db.engine.dispose()


def test_coordinate_migration_can_be_reversed(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "map-downgrade.db", monkeypatch)
    with app.app_context():
        upgrade()
        downgrade(revision="b37d5be5c2a1")
        columns = {column["name"] for column in inspect(db.engine).get_columns("printing_shops")}
        assert "latitude" not in columns
        assert "longitude" not in columns
        db.session.remove()
        db.engine.dispose()
