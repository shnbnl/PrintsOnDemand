"""Upgrade an existing account without resetting its password or identity."""

from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text

from app.extensions import db
from tests.test_stage6_migration import migration_app


def test_security_tables_upgrade_and_downgrade_preserve_existing_users(tmp_path, monkeypatch):
    app = migration_app(tmp_path, "security.db", monkeypatch)
    with app.app_context():
        upgrade(revision="b6a4e9d2c813")
        db.session.execute(text("""
            INSERT INTO users (id, name, email, password_hash, role, is_active,
                               professor_verification_status, student_delivery_preference,
                               created_at, updated_at)
            VALUES (1, 'Existing Customer', 'existing@example.edu', 'existing-hash', 'STUDENT', 1,
                    'PENDING', 0, '2026-10-19', '2026-10-19')
        """))
        db.session.commit()
        upgrade()
        assert {"auth_sessions", "rate_limit_buckets"} <= set(inspect(db.engine).get_table_names())
        assert db.session.execute(text("SELECT password_hash FROM users WHERE id=1")).scalar_one() == "existing-hash"
        db.session.execute(text("""
            INSERT INTO auth_sessions
              (token_hash,user_id,password_fingerprint,created_at,last_seen_at,expires_at,idle_seconds)
            VALUES (:token,1,:fingerprint,1,1,100,30)
        """), {"token": "a" * 64, "fingerprint": "b" * 64})
        db.session.commit()
        db.session.execute(text("DELETE FROM users WHERE id=1"))
        db.session.commit()
        assert db.session.execute(text("SELECT count(*) FROM auth_sessions")).scalar_one() == 0
        assert db.session.execute(text("PRAGMA foreign_key_check")).all() == []
        db.session.remove()
        downgrade(revision="b6a4e9d2c813")
        assert "auth_sessions" not in inspect(db.engine).get_table_names()
        db.engine.dispose()
