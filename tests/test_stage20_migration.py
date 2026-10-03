"""Professor delivery migration preserves old accounts, orders, and shop records."""

from flask_migrate import downgrade, upgrade
from sqlalchemy import text

from app.extensions import db
from tests.test_stage6_migration import migration_app


def test_existing_order_and_student_survive_professor_delivery_upgrade(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "stage20-existing.db", monkeypatch)
    with app.app_context():
        upgrade(revision="3f1a9d7c2b61")
        now = "2026-10-03 00:00:00"
        db.session.execute(text("""
            INSERT INTO users (id, name, email, password_hash, role, is_active, created_at, updated_at)
            VALUES (1, 'Existing Student', 'old@example.edu', '!', 'STUDENT', 1, :now, :now)
        """), {"now": now})
        db.session.execute(text("""
            INSERT INTO printing_shops (id, name, description, address, opening_time,
                closing_time, is_active, is_demo, created_at, updated_at)
            VALUES (1, 'Other Shop', '', 'Campus', '09:00:00', '17:00:00', 1, 0, :now, :now)
        """), {"now": now})
        db.session.execute(text("""
            INSERT INTO shop_services (id, shop_id, service_type, enabled)
            VALUES (1, 1, 'DIRECT_TO_PROFESSOR', 1)
        """))
        db.session.execute(text("""
            INSERT INTO professors (id, name, email, department, office, is_active,
                direct_send_approved, created_at, updated_at)
            VALUES (1, 'Old Professor', 'old-prof@example.edu', 'Engineering', 'Room 1',
                1, 1, :now, :now)
        """), {"now": now})
        db.session.execute(text("""
            INSERT INTO orders (id, user_id, shop_id, order_reference, shop_name, destination,
                professor_id, professor_name, professor_email, professor_department, professor_office,
                status, subtotal, rush_fee, fees_total, total, currency, created_at, updated_at)
            VALUES (1, 1, 1, 'POD-2026-STAGE20', 'Other Shop', 'PROFESSOR', 1,
                'Old Professor', 'old-prof@example.edu', 'Engineering', 'Room 1',
                'READY', 10, 0, 0, 10, 'PHP', :now, :now)
        """), {"now": now})
        db.session.commit()

        upgrade()
        assert db.session.execute(text(
            "SELECT accepts_student_deliveries FROM professors WHERE id = 1"
        )).scalar_one() == 0
        assert db.session.execute(text(
            "SELECT professor_recipient_type, professor_name FROM orders WHERE id = 1"
        )).one() == ("STUDENT_SELECTED", "Old Professor")
        assert db.session.execute(text(
            "SELECT enabled FROM shop_services WHERE id = 1"
        )).scalar_one() == 0
        assert db.session.execute(text(
            "SELECT id, role, professor_id FROM users WHERE id = 1"
        )).one() == (1, "STUDENT", None)
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.execute(text("""
            INSERT INTO users (id, name, email, password_hash, role, is_active,
                professor_id, created_at, updated_at)
            VALUES (2, 'Old Professor', 'old-prof@example.edu', '!', 'PROFESSOR', 1, 1, :now, :now)
        """), {"now": now})
        db.session.commit()
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.execute(text("DELETE FROM users WHERE id = 2"))
        db.session.commit()
        downgrade(revision="3f1a9d7c2b61")
        assert db.session.execute(text("SELECT professor_name FROM orders WHERE id = 1")).scalar_one() == "Old Professor"
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.remove()
        db.engine.dispose()
