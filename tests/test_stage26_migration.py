"""Stage 26 backfills only previously trusted, linked Professor accounts."""

from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text

from app.extensions import db
from tests.test_stage6_migration import migration_app


def test_stage26_populated_upgrade_and_downgrade(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "stage26-existing.db", monkeypatch)
    with app.app_context():
        upgrade(revision="c2d95e7a104b")
        now = "2026-10-04 00:00:00"
        for identifier, name, approved, active in (
            (1, "Verified", 1, 1), (2, "Unapproved", 0, 1), (3, "Inactive", 1, 0),
        ):
            db.session.execute(text("""
                INSERT INTO professors (id, name, email, is_active, direct_send_approved,
                    accepts_student_deliveries, created_at, updated_at)
                VALUES (:id, :name, :email, :active, :approved, 0, :now, :now)
            """), {"id": identifier, "name": name, "email": f"{name.lower()}@example.edu",
                   "active": active, "approved": approved, "now": now})
            db.session.execute(text("""
                INSERT INTO users (id, name, email, password_hash, role, is_active,
                    professor_id, created_at, updated_at)
                VALUES (:id, :name, :email, '!', 'PROFESSOR', 1, :id, :now, :now)
            """), {"id": identifier, "name": name, "email": f"{name.lower()}@example.edu", "now": now})
        db.session.execute(text("""
            INSERT INTO users (id, name, email, password_hash, role, is_active, created_at, updated_at)
            VALUES (4, 'Pending', 'pending@example.edu', '!', 'PROFESSOR', 1, :now, :now)
        """), {"now": now})
        db.session.commit()
        upgrade()
        assert "professor_verification_status" in {
            item["name"] for item in inspect(db.engine).get_columns("users")
        }
        assert db.session.execute(text("""
            SELECT professor_verification_status FROM users ORDER BY id
        """)).scalars().all() == ["VERIFIED", "PENDING", "PENDING", "PENDING"]
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        downgrade(revision="c2d95e7a104b")
        assert db.session.execute(text("SELECT count(*) FROM users")).scalar_one() == 4
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.remove()
        db.engine.dispose()
