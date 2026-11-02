"""Existing shops and recipient profiles survive the availability migration."""

from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text

from app.extensions import db
from test_stage6_migration import migration_app


def test_upgrade_and_downgrade_preserve_existing_shops_and_profiles(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "availability.db", monkeypatch)
    with app.app_context():
        upgrade(revision="ab14d7e93c20")
        db.session.execute(text("""
            INSERT INTO printing_shops (id, name, description, address, opening_time,
                closing_time, is_active, is_demo, created_at, updated_at)
            VALUES (9009, 'Existing Hours', '', 'Campus', '09:00:00', '18:00:00',
                    1, 0, '2026-11-03', '2026-11-03')
        """))
        db.session.execute(text("""
            INSERT INTO professors (id, name, email, department, faculty, office,
                is_active, direct_send_approved, accepts_student_deliveries, created_at, updated_at)
            VALUES (9009, 'Existing Professor', 'existing-migration@example.edu', 'MITL',
                    'Computer Engineering', 'Room 123', 1, 1, 1, '2026-11-03', '2026-11-03')
        """))
        db.session.execute(text("""
            INSERT INTO users (id, name, email, password_hash, role, is_active, created_at, updated_at)
            VALUES (9009, 'Existing Student', 'migration-student@example.edu', '!', 'STUDENT',
                    1, '2026-11-03', '2026-11-03')
        """))
        db.session.execute(text("""
            INSERT INTO orders (id, user_id, shop_id, professor_id, order_reference, shop_name,
                status, subtotal, rush_fee, fees_total, total, currency, created_at, updated_at)
            VALUES (9009, 9009, 9009, 9009, 'POD-2026-EXISTING', 'Existing Hours',
                    'PENDING_PAYMENT', 10, 0, 0, 10, 'PHP', '2026-11-03', '2026-11-03')
        """))
        db.session.commit()
        upgrade()
        assert db.session.execute(text("SELECT is_on_break FROM printing_shops WHERE id=9009")).scalar() == 0
        # Old unlinked profiles must not silently become approved staff recipients.
        assert db.session.execute(text("SELECT is_staff_managed FROM professors WHERE id=9009")).scalar() == 0
        db.session.commit()
        downgrade(revision="ab14d7e93c20")
        assert "is_on_break" not in {column["name"] for column in inspect(db.engine).get_columns("printing_shops")}
        assert db.session.execute(text("SELECT office FROM professors WHERE id=9009")).scalar() == "Room 123"
        assert db.session.execute(text("SELECT closing_time FROM printing_shops WHERE id=9009")).scalar() == "18:00:00"
        assert db.session.execute(text("SELECT shop_id, professor_id, total FROM orders WHERE id=9009")).one() == (9009, 9009, 10)
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.commit()
        upgrade()
        assert db.session.execute(text("SELECT is_on_break FROM printing_shops WHERE id=9009")).scalar() == 0
        db.session.remove()
        db.engine.dispose()
