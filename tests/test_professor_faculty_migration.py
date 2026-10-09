"""The faculty migration backfills verified professors without losing orders."""

from flask_migrate import upgrade
from sqlalchemy import inspect, text

from app.extensions import db
from tests.test_stage6_migration import migration_app


def test_upgrade_creates_missing_verified_profile_and_expands_faculty(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "professor-faculty.db", monkeypatch)
    with app.app_context():
        upgrade(revision="a91c5d07e3b2")
        db.session.execute(text("""
            INSERT INTO users (id, name, email, password_hash, role, is_active,
                               professor_department, professor_verification_status,
                               student_delivery_preference, created_at, updated_at)
            VALUES (1, 'Professor One', 'one@example.edu', '!', 'PROFESSOR', 1,
                    'CCIS', 'VERIFIED', 0, '2026-10-09', '2026-10-09')
        """))
        db.session.commit()
        upgrade()
        assert "professor_faculty" in {column["name"] for column in inspect(db.engine).get_columns("users")}
        profile = db.session.execute(text("""
            SELECT p.id, p.name, p.email, p.department, p.faculty, u.professor_id, u.professor_faculty
            FROM users u JOIN professors p ON p.id = u.professor_id WHERE u.id = 1
        """)).one()
        assert profile[1:] == ("Professor One", "one@example.edu", "CCIS", "CCIS", profile[0], "CCIS")
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.remove()
        db.engine.dispose()
