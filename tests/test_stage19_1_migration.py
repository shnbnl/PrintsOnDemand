"""Stage 19.1 coordinate precision migration preserves existing shops."""

from decimal import Decimal

from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text

from app.extensions import db
from tests.test_stage6_migration import migration_app


def _coordinate_types():
    columns = {column["name"]: column["type"] for column in inspect(db.engine).get_columns("printing_shops")}
    return columns["latitude"], columns["longitude"]


def test_fresh_migration_creates_fifteen_decimal_coordinate_columns(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "fresh-coordinate-precision.db", monkeypatch)
    with app.app_context():
        upgrade()
        assert all(str(column).upper().startswith("VARCHAR(32)") for column in _coordinate_types())
        assert db.session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        db.session.remove()
        db.engine.dispose()


def test_precision_migration_preserves_existing_shop_data_and_downgrades(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "existing-coordinate-precision.db", monkeypatch)
    with app.app_context():
        upgrade(revision="a7e918c4b250")
        now = "2026-10-03 00:00:00"
        db.session.execute(text("""
            INSERT INTO printing_shops
                (id, name, description, address, opening_time, closing_time,
                 latitude, longitude, is_active, is_demo, created_at, updated_at)
            VALUES (1, 'Existing precision shop', 'Kept description', 'Kept address',
                    '09:00:00', '17:00:00', 14.243035, 121.112953, 1, 1, :now, :now)
        """), {"now": now})
        db.session.execute(text("""
            INSERT INTO shop_services (id, shop_id, service_type, enabled)
            VALUES (1, 1, 'PICKUP', 1)
        """))
        db.session.commit()
        assert db.session.execute(text("SELECT count(*) FROM shop_services WHERE shop_id = 1")).scalar_one() == 1

        upgrade()
        assert all(str(column).upper().startswith("VARCHAR(32)") for column in _coordinate_types())
        shop = db.session.execute(text("""
            SELECT name, description, address, latitude, longitude, is_active, is_demo
            FROM printing_shops WHERE id = 1
        """)).one()
        assert tuple(shop[:3]) == ("Existing precision shop", "Kept description", "Kept address")
        assert Decimal(str(shop.latitude)) == Decimal("14.243035")
        assert Decimal(str(shop.longitude)) == Decimal("121.112953")
        assert (shop.is_active, shop.is_demo) == (1, 1)
        assert db.session.execute(text("SELECT service_type FROM shop_services WHERE shop_id = 1")).scalar_one() == "PICKUP"
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []

        downgrade(revision="a7e918c4b250")
        columns = {column["name"]: column["type"] for column in inspect(db.engine).get_columns("printing_shops")}
        assert columns["latitude"].precision == columns["longitude"].precision == 9
        assert columns["latitude"].scale == columns["longitude"].scale == 6
        assert db.session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        assert db.session.execute(text("SELECT service_type FROM shop_services WHERE shop_id = 1")).scalar_one() == "PICKUP"
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.remove()
        db.engine.dispose()
