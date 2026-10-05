"""Shop-photo schema adds optional fields without rebuilding populated shops."""

from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text

from app.extensions import db
from tests.test_stage6_migration import migration_app


def test_populated_shop_photo_upgrade_and_downgrade(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "shop-photo.db", monkeypatch)
    with app.app_context():
        upgrade(revision="d7f82a46b901")
        db.session.execute(text("""
            INSERT INTO printing_shops
                (id, name, description, address, opening_time, closing_time,
                 is_active, is_demo, created_at, updated_at)
            VALUES (1, 'Existing Shop', 'Original description', 'Campus Road',
                    '09:00:00', '17:00:00', 1, 1, '2026-10-04', '2026-10-04')
        """))
        db.session.execute(text("""
            INSERT INTO printing_shops
                (id, name, description, address, opening_time, closing_time,
                 is_active, is_demo, created_at, updated_at)
            VALUES (2, 'Blue and Silver Bookstore', 'Original description',
                    'Demo location near Mapúa Malayan Colleges Laguna',
                    '09:00:00', '17:00:00', 1, 1, '2026-10-04', '2026-10-04'),
                   (3, 'Unrelated Shop', 'Original description',
                    'Demo location near Mapúa Malayan Colleges Laguna',
                    '09:00:00', '17:00:00', 1, 0, '2026-10-04', '2026-10-04')
        """))
        db.session.commit()
        upgrade()
        columns = {item["name"] for item in inspect(db.engine).get_columns("printing_shops")}
        assert {"photo_data", "photo_mime", "photo_digest"} <= columns
        row = db.session.execute(text("""
            SELECT name, description, is_demo, photo_data, photo_mime, photo_digest
            FROM printing_shops WHERE id = 1
        """)).one()
        assert row == ("Existing Shop", "Original description", 1, None, None, None)
        addresses = db.session.execute(text(
            "SELECT id, address FROM printing_shops ORDER BY id"
        )).all()
        assert addresses == [
            (1, "Campus Road"),
            (2, "Near Mapúa Malayan Colleges Laguna"),
            (3, "Demo location near Mapúa Malayan Colleges Laguna"),
        ]
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        downgrade(revision="d7f82a46b901")
        assert db.session.execute(text("SELECT name FROM printing_shops WHERE id = 1")).scalar_one() == "Existing Shop"
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.remove()
        db.engine.dispose()
