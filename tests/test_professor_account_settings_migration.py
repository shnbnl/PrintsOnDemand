"""Existing account rows survive professor-preference schema upgrade/downgrade."""

from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text

from app.extensions import db
from tests.test_stage6_migration import migration_app


def test_professor_preferences_migration_preserves_existing_account(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "professor-preferences.db", monkeypatch)
    with app.app_context():
        upgrade(revision="91d2e4b6a7c8")
        db.session.execute(text("""
            INSERT INTO users (id, name, email, password_hash, role, is_active, created_at, updated_at)
            VALUES (1, 'Existing Professor', 'prof@example.edu', '!', 'PROFESSOR', 1,
                '2026-10-04 00:00:00', '2026-10-04 00:00:00')
        """))
        db.session.commit()
        upgrade()
        columns = {column["name"] for column in inspect(db.engine).get_columns("users")}
        assert {"professor_department", "student_delivery_preference"} <= columns
        assert db.session.execute(text("""
            SELECT name, professor_department, student_delivery_preference FROM users WHERE id = 1
        """)).one() == ("Existing Professor", None, 0)
        db.session.execute(text("""
            UPDATE users SET professor_department = 'Computer Science', student_delivery_preference = 1
            WHERE id = 1
        """))
        db.session.commit()
        downgrade(revision="91d2e4b6a7c8")
        assert db.session.execute(text("SELECT name FROM users WHERE id = 1")).scalar_one() == "Existing Professor"
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.remove()
        db.engine.dispose()

