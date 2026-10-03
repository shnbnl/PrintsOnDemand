"""Fresh and Stage 9 database upgrades for public payment settings."""

from flask_migrate import upgrade
from sqlalchemy import inspect, text

from app.extensions import db
from test_stage6_migration import migration_app


def test_fresh_stage10_database(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "stage10-fresh.db", monkeypatch)
    with app.app_context():
        upgrade()
        assert "payment_settings" in inspect(db.engine).get_table_names()
        assert db.session.execute(text("SELECT count(*) FROM payment_settings")).scalar_one() == 0
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.remove()
        db.engine.dispose()


def test_stage9_upgrade_preserves_orders_and_payments(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "stage10-existing.db", monkeypatch)
    with app.app_context():
        upgrade(revision="92c4f0a1d9e7")
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
            INSERT INTO uploaded_files (id, user_id, original_filename, stored_filename,
                storage_key, mime_type, file_extension, file_size, sha256, created_at, updated_at)
            VALUES (1, 1, 'old.pdf', 'old.pdf', 'old.pdf', 'application/pdf',
                'pdf', 5, :sha, :now, :now)
        """), {"sha": "a" * 64, "now": now})
        db.session.execute(text("""
            INSERT INTO orders (id, user_id, shop_id, order_reference, shop_name,
                status, subtotal, rush_fee, fees_total, total, currency, created_at, updated_at)
            VALUES (1, 1, 1, 'POD-2026-STAGE10', 'Existing Shop',
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
        assert db.session.execute(text("SELECT count(*) FROM payment_settings")).scalar_one() == 0
        assert db.session.execute(text("SELECT count(*) FROM order_items")).scalar_one() == 1
        order = db.session.execute(text("SELECT order_reference, total, status FROM orders")).one()
        assert (order.order_reference, float(order.total), order.status) == (
            "POD-2026-STAGE10", 6.75, "PENDING_PAYMENT"
        )
        payment = db.session.execute(text("SELECT payment_status, amount FROM payments")).one()
        assert (payment.payment_status, float(payment.amount)) == ("SUBMITTED", 6.75)
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.remove()
        db.engine.dispose()
