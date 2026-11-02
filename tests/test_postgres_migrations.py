"""Exercise the actual migration chain on an explicitly disposable PostgreSQL DB.

Set POSTGRES_MIGRATION_TEST_URL to an empty test database, never a deployed DB.
"""

import os

from flask_migrate import upgrade
from psycopg import ClientCursor
import pytest
from sqlalchemy import inspect, select, text

from app import create_app
from app.config import TestingConfig
from app.extensions import db
from app.models import User
from test_auth import PASSWORD, csrf_token, register


@pytest.fixture
def postgres_migration_app(monkeypatch):
    url = os.getenv("POSTGRES_MIGRATION_TEST_URL")
    if not url:
        pytest.skip("Set POSTGRES_MIGRATION_TEST_URL to an empty disposable PostgreSQL database")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DATABASE_POOL_MODE", "null")
    monkeypatch.setenv("FORCE_HTTPS", "false")
    monkeypatch.setenv("PROXY_FIX_HOPS", "0")

    class MigrationTestingConfig(TestingConfig):
        SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {
            "prepare_threshold": None, "cursor_factory": ClientCursor,
        }}

    app = create_app(MigrationTestingConfig)
    with app.app_context():
        if db.engine.dialect.name != "postgresql":
            pytest.fail("Migration integration tests require PostgreSQL")
        inspector = inspect(db.engine)
        if inspector.get_table_names() or "pod_security" in inspector.get_schema_names():
            pytest.fail("Refusing a nonempty DB; provide an empty disposable PostgreSQL database")
        try:
            yield app
        finally:
            db.session.remove()
            with db.engine.begin() as connection:
                if "pod_security" in inspect(connection).get_schema_names():
                    connection.exec_driver_sql("DROP SCHEMA pod_security CASCADE")
            db.drop_all()
            with db.engine.begin() as connection:
                connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
            db.engine.dispose()


def test_fresh_postgres_upgrade_supports_registration_and_login(postgres_migration_app):
    upgrade()
    assert db.session.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "ab14d7e93c20"
    assert set(db.metadata.tables) <= set(inspect(db.session.connection()).get_table_names())
    db.session.remove()

    client = postgres_migration_app.test_client()
    response = register(client)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/login")
    user = db.session.scalar(select(User).where(User.email == "student@example.com"))
    assert user is not None and user.check_password(PASSWORD)
    db.session.remove()
    response = client.post("/auth/login", data={
        "csrf_token": csrf_token(client.get("/auth/login")),
        "email": "student@example.com", "password": PASSWORD,
    })
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/student")


def test_postgres_upgrade_only_verifies_active_approved_professor_links(postgres_migration_app):
    upgrade(revision="c2d95e7a104b")
    for identifier, active, approved in ((1, True, True), (2, True, False), (3, False, True), (4, True, True)):
        db.session.execute(text("""
            INSERT INTO professors
                (id, name, email, is_active, direct_send_approved, created_at, updated_at)
            VALUES (:id, :name, :email, :active, :approved, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """), {"id": identifier, "name": f"Professor {identifier}",
               "email": f"professor{identifier}@example.edu", "active": active, "approved": approved})
    for identifier, role, profile_id in (
        (1, "PROFESSOR", 1), (2, "PROFESSOR", 2), (3, "PROFESSOR", 3),
        (4, "PROFESSOR", None), (5, "STUDENT", 4),
    ):
        db.session.execute(text("""
            INSERT INTO users
                (id, name, email, password_hash, role, is_active, professor_id, created_at, updated_at)
            VALUES (:id, :name, :email, '!', :role, TRUE, :profile_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """), {"id": identifier, "name": f"Account {identifier}",
               "email": f"account{identifier}@example.edu", "role": role, "profile_id": profile_id})
    db.session.commit()
    upgrade()
    statuses = db.session.execute(text(
        "SELECT professor_verification_status FROM users ORDER BY id"
    )).scalars().all()
    assert statuses == ["VERIFIED", "PENDING", "PENDING", "PENDING", "PENDING"]
    assert db.session.execute(text("SELECT count(*) FROM professors")).scalar_one() == 4
