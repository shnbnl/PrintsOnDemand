"""Stage 21 Faculty and handoff migration preserves existing data."""

from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text

from app.extensions import db
from tests.test_stage6_migration import migration_app


def test_stage21_fresh_upgrade(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "stage21-fresh.db", monkeypatch)
    with app.app_context():
        upgrade()
        assert {"faculty"} <= {column["name"] for column in inspect(db.engine).get_columns("professors")}
        assert {"professor_faculty", "delivered_at"} <= {
            column["name"] for column in inspect(db.engine).get_columns("orders")
        }
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.remove()
        db.engine.dispose()


def test_stage21_existing_order_survives_upgrade_and_downgrade(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "stage21-existing.db", monkeypatch)
    with app.app_context():
        upgrade(revision="8d41c20e7f09")
        now = "2026-10-03 00:00:00"
        db.session.execute(text("""
            INSERT INTO users (id, name, email, password_hash, role, is_active, created_at, updated_at)
            VALUES (1, 'Existing Student', 'student@example.edu', '!', 'STUDENT', 1, :now, :now)
        """), {"now": now})
        db.session.execute(text("""
            INSERT INTO printing_shops (id, name, description, address, opening_time,
                closing_time, is_active, is_demo, created_at, updated_at)
            VALUES (1, 'Blue and Silver Bookstore', '', 'Campus', '09:00:00', '17:00:00', 1, 0, :now, :now)
        """), {"now": now})
        db.session.execute(text("""
            INSERT INTO professors (id, name, email, department, office, is_active,
                direct_send_approved, accepts_student_deliveries, created_at, updated_at)
            VALUES (1, 'Existing Professor', 'prof@example.edu', 'Engineering', 'Room 1',
                1, 1, 1, :now, :now)
        """), {"now": now})
        db.session.execute(text("""
            INSERT INTO orders (id, user_id, shop_id, order_reference, shop_name, destination,
                professor_id, professor_recipient_type, professor_name, professor_email,
                status, subtotal, rush_fee, fees_total, total, currency, created_at, updated_at)
            VALUES (1, 1, 1, 'POD-2026-OLD21', 'Blue and Silver Bookstore', 'PROFESSOR',
                1, 'STUDENT_SELECTED', 'Existing Professor', 'prof@example.edu',
                'READY', 10, 0, 0, 10, 'PHP', :now, :now)
        """), {"now": now})
        db.session.commit()

        upgrade()
        assert db.session.execute(text("""
            SELECT professor_name, professor_recipient_type, professor_faculty, delivered_at, status
            FROM orders WHERE id = 1
        """)).one() == ("Existing Professor", "STUDENT_SELECTED", None, None, "READY")
        assert db.session.execute(text("SELECT faculty FROM professors WHERE id = 1")).scalar_one_or_none() is None
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.execute(text("UPDATE professors SET faculty = 'CCIS' WHERE id = 1"))
        db.session.execute(text("UPDATE orders SET status = 'DELIVERED', professor_faculty = 'CCIS' WHERE id = 1"))
        db.session.commit()
        assert db.session.execute(text("SELECT status FROM orders WHERE id = 1")).scalar_one() == "DELIVERED"
        db.session.execute(text("UPDATE orders SET status = 'READY' WHERE id = 1"))
        db.session.commit()
        downgrade(revision="8d41c20e7f09")
        assert db.session.execute(text("SELECT professor_name FROM orders WHERE id = 1")).scalar_one() == "Existing Professor"
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.remove()
        db.engine.dispose()
