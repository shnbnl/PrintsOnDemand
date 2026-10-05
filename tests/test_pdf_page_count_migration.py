"""PDF page-count columns are additive and preserve existing file metadata."""

from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text

from app.extensions import db
from tests.test_stage6_migration import migration_app


def test_pdf_page_count_migration_is_additive_and_reversible(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "pdf-page-count.db", monkeypatch)
    with app.app_context():
        upgrade(revision="e48b13a6d9c2")
        db.session.execute(text("""
            INSERT INTO users (id, name, email, password_hash, role, is_active, created_at, updated_at)
            VALUES (1, 'Existing Student', 'existing@example.edu', '!', 'STUDENT', 1,
                    '2026-10-05', '2026-10-05')
        """))
        db.session.execute(text("""
            INSERT INTO uploaded_files (id, user_id, original_filename, stored_filename,
                storage_key, mime_type, file_extension, file_size, sha256, created_at, updated_at)
            VALUES (1, 1, 'existing.pdf', 'a.pdf', :key, 'application/pdf', 'pdf', 10,
                    :sha, '2026-10-05', '2026-10-05')
        """), {"key": "a" * 32 + ".pdf", "sha": "b" * 64})
        db.session.commit()

        upgrade()
        uploaded_columns = {column["name"] for column in inspect(db.engine).get_columns("uploaded_files")}
        order_item_columns = {column["name"] for column in inspect(db.engine).get_columns("order_items")}
        assert "pdf_page_count" in uploaded_columns
        assert {"pdf_page_count", "total_printed_pages"} <= order_item_columns
        assert db.session.execute(text("""
            SELECT original_filename, file_size, sha256, pdf_page_count
            FROM uploaded_files WHERE id = 1
        """)).one() == ("existing.pdf", 10, "b" * 64, None)

        downgrade(revision="e48b13a6d9c2")
        assert "pdf_page_count" not in {
            column["name"] for column in inspect(db.engine).get_columns("uploaded_files")
        }
        assert "total_printed_pages" not in {
            column["name"] for column in inspect(db.engine).get_columns("order_items")
        }
        assert db.session.execute(text(
            "SELECT original_filename FROM uploaded_files WHERE id = 1"
        )).scalar_one() == "existing.pdf"
        db.session.remove()
        db.engine.dispose()
