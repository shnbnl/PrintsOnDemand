"""Stage 18 review audit migration preserves existing orders and payments."""

from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text

from app.extensions import db
from test_stage6_migration import migration_app


OLD_HEAD = "6c2a09d4f518"


def test_fresh_payment_review_migration_and_downgrade(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "stage18-fresh.db", monkeypatch)
    with app.app_context():
        upgrade()
        columns = {column["name"] for column in inspect(db.engine).get_columns("payments")}
        assert {"submitted_at", "reviewed_at", "reviewed_by_id", "rejection_reason"} <= columns
        assert any(fk["referred_table"] == "users" and fk["constrained_columns"] == ["reviewed_by_id"]
                   for fk in inspect(db.engine).get_foreign_keys("payments"))
        downgrade(revision=OLD_HEAD)
        columns = {column["name"] for column in inspect(db.engine).get_columns("payments")}
        assert "reviewed_by_id" not in columns and "submitted_at" not in columns
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.remove()
        db.engine.dispose()


def test_populated_submitted_payment_survives_upgrade_and_downgrade(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "stage18-existing.db", monkeypatch)
    with app.app_context():
        upgrade(revision=OLD_HEAD)
        now = "2026-10-03 00:00:00"
        db.session.execute(text("""
            INSERT INTO users (id, name, email, password_hash, role, is_active, created_at, updated_at)
            VALUES (1, 'Existing Student', 'stage18-old@example.edu', '!', 'STUDENT', 1, :now, :now)
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
            VALUES (1, 1, 1, 'POD-2026-STAGE18', 'Existing Shop',
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
            SELECT payment_status, payment_reference, amount, currency, submitted_at,
                   reviewed_at, reviewed_by_id, rejection_reason FROM payments WHERE id = 1
        """)).one()
        assert (row.payment_status, row.payment_reference, float(row.amount), row.currency) == (
            "SUBMITTED", "LEGACY-REF", 6.75, "PHP")
        assert row.submitted_at is not None
        assert row.reviewed_at is row.reviewed_by_id is row.rejection_reason is None
        assert db.session.execute(text("SELECT total FROM orders WHERE id = 1")).scalar_one() == 6.75
        assert db.session.execute(text("SELECT count(*) FROM order_items")).scalar_one() == 1
        downgrade(revision=OLD_HEAD)
        row = db.session.execute(text("SELECT payment_status, payment_reference, amount FROM payments WHERE id = 1")).one()
        assert (row.payment_status, row.payment_reference, float(row.amount)) == ("SUBMITTED", "LEGACY-REF", 6.75)
        assert db.session.execute(text("SELECT count(*) FROM order_items")).scalar_one() == 1
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.remove()
        db.engine.dispose()
