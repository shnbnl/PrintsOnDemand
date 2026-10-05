"""Shop payment migration preserves existing records and isolates QR data."""

from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text

from app.extensions import db
from tests.test_stage6_migration import migration_app


def test_fresh_payment_upgrade(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "shop-payment-fresh.db", monkeypatch)
    with app.app_context():
        upgrade()
        columns = {item["name"] for item in inspect(db.engine).get_columns("printing_shops")}
        assert {"cash_enabled", "online_enabled", "payment_qr_data", "payment_qr_digest"} <= columns
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.remove()
        db.engine.dispose()


def test_populated_payment_upgrade_and_downgrade(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "shop-payment-existing.db", monkeypatch)
    with app.app_context():
        upgrade(revision="6d9f3a8c12e4")
        now = "2026-10-03 00:00:00"
        db.session.execute(text("""
            INSERT INTO users (id, name, email, password_hash, role, is_active, created_at, updated_at)
            VALUES (1, 'Existing Student', 'student@example.edu', '!', 'STUDENT', 1, :now, :now)
        """), {"now": now})
        for index, name in enumerate(("Blue and Silver Bookstore", "CHALECOSPOT"), 1):
            db.session.execute(text("""
                INSERT INTO printing_shops (id, name, description, address, opening_time,
                    closing_time, is_active, is_demo, created_at, updated_at)
                VALUES (:id, :name, '', 'Campus', '09:00:00', '17:00:00', 1, 0, :now, :now)
            """), {"id": index, "name": name, "now": now})
        db.session.execute(text("""
            INSERT INTO payment_settings (id, online_enabled, online_instructions,
                online_account_name, online_destination, onsite_instructions, updated_at)
            VALUES (1, 1, 'Legacy instructions', 'Legacy account', 'LEGACY-123', 'Cash counter', :now)
        """), {"now": now})
        db.session.execute(text("""
            INSERT INTO orders (id, user_id, shop_id, order_reference, shop_name, status,
                subtotal, rush_fee, fees_total, total, currency, created_at, updated_at)
            VALUES (1, 1, 1, 'POD-2026-SHOPPAY', 'Blue and Silver Bookstore',
                'PENDING_PAYMENT', 10, 0, 0, 10, 'PHP', :now, :now)
        """), {"now": now})
        db.session.execute(text("""
            INSERT INTO payments (id, order_id, payment_method, payment_status, amount,
                currency, payment_reference, created_at, updated_at)
            VALUES (1, 1, 'ONLINE', 'SUBMITTED', 10, 'PHP', 'OLD-REF', :now, :now)
        """), {"now": now})
        db.session.commit()

        upgrade()
        shops = db.session.execute(text("""
            SELECT id, online_enabled, online_account_name, online_account_reference,
                payment_qr_data, payment_qr_digest FROM printing_shops ORDER BY id
        """)).all()
        assert [item[0] for item in shops] == [1, 2]
        assert all(item[1:4] == (1, "Legacy account", "LEGACY-123") for item in shops)
        assert all(item[4].startswith(b"\x89PNG") for item in shops)
        assert shops[0][5] != shops[1][5]
        assert db.session.execute(text("SELECT payment_reference FROM payments WHERE id=1")).scalar_one() == "OLD-REF"
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []

        downgrade(revision="6d9f3a8c12e4")
        assert db.session.execute(text("SELECT name FROM printing_shops WHERE id=1")).scalar_one() == "Blue and Silver Bookstore"
        assert db.session.execute(text("SELECT payment_reference FROM payments WHERE id=1")).scalar_one() == "OLD-REF"
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.remove()
        db.engine.dispose()
