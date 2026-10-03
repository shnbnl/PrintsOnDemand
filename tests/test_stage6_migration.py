"""Stage 6 migration must preserve Stage 5 orders and their dependent items."""

from flask_migrate import upgrade
from sqlalchemy import inspect, text

from app import create_app
from app.config import DevelopmentConfig
from app.extensions import db


def migration_app(tmp_path, name, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    config = type("MigrationCheckConfig", (DevelopmentConfig,), {
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / name).as_posix()}",
        "UPLOAD_STORAGE_ROOT": str(tmp_path / "uploads"),
    })
    return create_app(config)


def test_fresh_chain_creates_professor_relationship(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "fresh.db", monkeypatch)
    with app.app_context():
        upgrade()
        tables = set(inspect(db.engine).get_table_names())
        assert {
            "users", "printing_shops", "print_prices", "uploaded_files",
            "print_configurations", "orders", "order_items", "professors",
        } <= tables
        assert any(
            fk["referred_table"] == "professors"
            for fk in inspect(db.engine).get_foreign_keys("orders")
        )
        db.session.remove()
        db.engine.dispose()


def test_existing_stage5_order_and_item_survive_upgrade(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "existing.db", monkeypatch)
    with app.app_context():
        upgrade(revision="0d4ae5b2a00c")
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
            VALUES (1, 1, 1, 'POD-2026-EXISTING001', 'Existing Shop',
                    'PENDING_PAYMENT', 6.75, 0, 0, 6.75, 'PHP', :now, :now)
        """), {"now": now})
        db.session.execute(text("""
            INSERT INTO order_items
                (id, order_id, uploaded_file_id, original_filename, paper_size,
                 color_mode, quantity, is_rush, unit_price, line_total, created_at, updated_at)
            VALUES (1, 1, 1, 'old.pdf', 'A4', 'GRAYSCALE', 3, 0, 2.25, 6.75, :now, :now)
        """), {"now": now})
        db.session.commit()

        upgrade()
        order = db.session.execute(text("""
            SELECT order_reference, total, destination, professor_id
            FROM orders WHERE id = 1
        """)).one()
        assert order.order_reference == "POD-2026-EXISTING001"
        assert float(order.total) == 6.75
        assert order.destination is None and order.professor_id is None
        assert db.session.execute(text("SELECT count(*) FROM order_items")).scalar_one() == 1
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.remove()
        db.engine.dispose()
