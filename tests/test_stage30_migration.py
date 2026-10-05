"""Stage 30 staging marker preserves populated private-file data."""

from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text

from app.extensions import db
from tests.test_stage6_migration import migration_app


def test_checkout_staging_upgrade_and_downgrade_preserve_legacy_rows(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "stage30-existing.db", monkeypatch)
    with app.app_context():
        upgrade(revision="f4a93d81c2e0")
        db.session.execute(text("""
            INSERT INTO users (id, name, email, password_hash, role, is_active, created_at, updated_at)
            VALUES (1, 'Existing Student', 'existing@example.edu', '!', 'STUDENT', 1, '2026-10-05', '2026-10-05')
        """))
        db.session.execute(text("""
            INSERT INTO uploaded_files (id, user_id, original_filename, stored_filename,
                storage_key, mime_type, file_extension, file_size, sha256, created_at, updated_at)
            VALUES (1, 1, 'historical.pdf', :key, :key, 'application/pdf', 'pdf', 11, :sha,
                '2026-10-05', '2026-10-05')
        """), {"key": "a" * 32 + ".pdf", "sha": "b" * 64})
        db.session.commit()
        upgrade()
        columns = {column["name"] for column in inspect(db.engine).get_columns("uploaded_files")}
        assert "checkout_staged_at" in columns
        assert db.session.execute(text("""
            SELECT original_filename, storage_key, checkout_staged_at FROM uploaded_files WHERE id = 1
        """)).one() == ("historical.pdf", "a" * 32 + ".pdf", None)
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        downgrade(revision="f4a93d81c2e0")
        assert "checkout_staged_at" not in {column["name"] for column in inspect(db.engine).get_columns("uploaded_files")}
        assert db.session.execute(text("SELECT original_filename FROM uploaded_files WHERE id = 1")).scalar_one() == "historical.pdf"
        db.session.remove()
        db.engine.dispose()
