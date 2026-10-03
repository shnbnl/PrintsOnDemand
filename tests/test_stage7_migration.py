"""Fresh payment schema and upgrade with legacy and professor orders."""

from flask_migrate import upgrade
from sqlalchemy import inspect, text

from app.extensions import db
from test_stage6_migration import migration_app


def test_fresh_chain_creates_payment_schema(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "stage7-fresh.db", monkeypatch)
    with app.app_context():
        upgrade()
        tables = set(inspect(db.engine).get_table_names())
        assert {"orders", "order_items", "professors", "payments"} <= tables
        assert any(
            fk["referred_table"] == "orders"
            for fk in inspect(db.engine).get_foreign_keys("payments")
        )
        db.session.remove()
        db.engine.dispose()


def test_stage6_upgrade_preserves_existing_orders_and_professor(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "stage7-existing.db", monkeypatch)
    with app.app_context():
        upgrade(revision="efaa90779826")
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
            INSERT INTO professors
                (id, name, email, department, office, is_active,
                 direct_send_approved, created_at, updated_at)
            VALUES (1, 'Demo Professor', 'demo@example.edu', 'Engineering',
                    'Room 204', 1, 1, :now, :now)
        """), {"now": now})
        db.session.execute(text("""
            INSERT INTO uploaded_files
                (id, user_id, original_filename, stored_filename, storage_key,
                 mime_type, file_extension, file_size, sha256, created_at, updated_at)
            VALUES (1, 1, 'old.pdf', 'old.pdf', 'old.pdf', 'application/pdf',
                    'pdf', 5, :sha, :now, :now)
        """), {"sha": "a" * 64, "now": now})
        db.session.execute(text("""
            INSERT INTO orders
                (id, user_id, shop_id, order_reference, shop_name, status,
                 subtotal, rush_fee, fees_total, total, currency, created_at, updated_at)
            VALUES (1, 1, 1, 'POD-2026-LEGACY', 'Existing Shop',
                    'PENDING_PAYMENT', 6.75, 0, 0, 6.75, 'PHP', :now, :now)
        """), {"now": now})
        db.session.execute(text("""
            INSERT INTO orders
                (id, user_id, shop_id, order_reference, shop_name, destination,
                 professor_id, professor_name, professor_email, professor_department,
                 professor_office, status, subtotal, rush_fee, fees_total, total,
                 currency, created_at, updated_at)
            VALUES (2, 1, 1, 'POD-2026-PROFESSOR', 'Existing Shop', 'PROFESSOR',
                    1, 'Demo Professor', 'demo@example.edu', 'Engineering',
                    'Room 204', 'PENDING_PAYMENT', 8.00, 0, 0, 8.00,
                    'PHP', :now, :now)
        """), {"now": now})
        db.session.execute(text("""
            INSERT INTO order_items
                (id, order_id, uploaded_file_id, original_filename, paper_size,
                 color_mode, quantity, is_rush, unit_price, line_total, created_at, updated_at)
            VALUES (1, 1, 1, 'old.pdf', 'A4', 'GRAYSCALE', 3, 0, 2.25, 6.75, :now, :now)
        """), {"now": now})
        db.session.commit()

        upgrade()
        orders = db.session.execute(text("""
            SELECT id, total, destination, professor_id, professor_name
            FROM orders ORDER BY id
        """)).all()
        assert len(orders) == 2
        assert float(orders[0].total) == 6.75 and orders[0].professor_id is None
        assert orders[1].destination == "PROFESSOR"
        assert orders[1].professor_id == 1
        assert orders[1].professor_name == "Demo Professor"
        assert db.session.execute(text("SELECT count(*) FROM order_items")).scalar_one() == 1
        assert db.session.execute(text("SELECT count(*) FROM payments")).scalar_one() == 0
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.remove()
        db.engine.dispose()
