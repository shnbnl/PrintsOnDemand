"""Stage 9 migration preserves Stage 8 orders, items, and payments."""

from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text

from app.extensions import db
from test_stage6_migration import migration_app


def test_fresh_stage9_migration(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "stage9-fresh.db", monkeypatch)
    with app.app_context():
        upgrade()
        columns = {column["name"] for column in inspect(db.engine).get_columns("orders")}
        assert {"processing_started_at", "ready_at", "completed_at"} <= columns
        checks = {check["name"]: check["sqltext"] for check in inspect(db.engine).get_check_constraints("orders")}
        assert "COMPLETED" in checks["order_status"]
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []

        db.session.remove()
        db.engine.dispose()


def test_upgrade_from_stage8_preserves_order_items_payment_and_professor(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "stage9-existing.db", monkeypatch)
    with app.app_context():
        upgrade(revision="6fb08dfd51de")
        now = "2026-10-03 00:00:00"
        db.session.execute(text("""
            INSERT INTO users (id, name, email, password_hash, role, is_active, created_at, updated_at)
            VALUES (1, 'Existing Student', 'existing@example.edu', '!', 'STUDENT', 1, :now, :now)
        """), {"now": now})
        db.session.execute(text("""
            INSERT INTO printing_shops (id, name, description, address, opening_time,
                closing_time, is_active, is_demo, created_at, updated_at)
            VALUES (1, 'Existing Shop', '', 'Campus', '09:00:00', '17:00:00', 1, 0, :now, :now)
        """), {"now": now})
        db.session.execute(text("""
            INSERT INTO professors (id, name, email, department, office, is_active,
                direct_send_approved, created_at, updated_at)
            VALUES (1, 'Professor Snapshot', 'prof@example.edu', 'Engineering',
                'Room 204', 1, 1, :now, :now)
        """), {"now": now})
        db.session.execute(text("""
            INSERT INTO uploaded_files (id, user_id, original_filename, stored_filename,
                storage_key, mime_type, file_extension, file_size, sha256, created_at, updated_at)
            VALUES (1, 1, 'old.pdf', 'old.pdf', 'old.pdf', 'application/pdf',
                'pdf', 5, :sha, :now, :now)
        """), {"sha": "a" * 64, "now": now})
        db.session.execute(text("""
            INSERT INTO orders (id, user_id, shop_id, order_reference, shop_name,
                destination, professor_id, professor_name, professor_email,
                professor_department, professor_office, status, subtotal, rush_fee,
                fees_total, total, currency, created_at, updated_at)
            VALUES (1, 1, 1, 'POD-2026-STAGE9', 'Existing Shop', 'PROFESSOR',
                1, 'Professor Snapshot', 'prof@example.edu', 'Engineering', 'Room 204',
                'PENDING_PAYMENT', 6.75, 0, 0, 6.75, 'PHP', :now, :now)
        """), {"now": now})
        db.session.execute(text("""
            INSERT INTO order_items (id, order_id, uploaded_file_id, original_filename,
                paper_size, color_mode, quantity, is_rush, unit_price, line_total,
                created_at, updated_at)
            VALUES (1, 1, 1, 'old.pdf', 'A4', 'GRAYSCALE', 3, 0, 2.25, 6.75, :now, :now)
        """), {"now": now})
        db.session.execute(text("""
            INSERT INTO payments (id, order_id, payment_method, payment_status, amount,
                currency, payment_reference, created_at, updated_at)
            VALUES (1, 1, 'ONLINE', 'SUBMITTED', 6.75, 'PHP', 'LEGACY-REF', :now, :now)
        """), {"now": now})
        db.session.commit()

        upgrade()
        row = db.session.execute(text("""
            SELECT order_reference, professor_name, status, processing_started_at,
                ready_at, completed_at FROM orders WHERE id = 1
        """)).one()
        assert row.order_reference == "POD-2026-STAGE9"
        assert row.professor_name == "Professor Snapshot"
        assert row.status == "PENDING_PAYMENT"
        assert row.processing_started_at is row.ready_at is row.completed_at is None
        assert db.session.execute(text("SELECT count(*) FROM order_items")).scalar_one() == 1
        payment = db.session.execute(text("SELECT payment_status, payment_reference, amount FROM payments")).one()
        assert payment.payment_status == "SUBMITTED" and payment.payment_reference == "LEGACY-REF"
        assert float(payment.amount) == 6.75
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        downgrade(revision="6fb08dfd51de")
        assert db.session.execute(text("SELECT count(*) FROM order_items")).scalar_one() == 1
        assert db.session.execute(text("SELECT count(*) FROM payments")).scalar_one() == 1
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.remove()
        db.engine.dispose()
