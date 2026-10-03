"""Foundation behavior and configuration checks."""

import pytest
from sqlalchemy import text

from app import create_app
from app.config import ProductionConfig
from app.extensions import db


def test_application_creation_and_test_database(test_app):
    assert test_app.testing is True
    assert test_app.config["ENV_NAME"] == "testing"
    assert test_app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite://"
    assert test_app.config["SECRET_KEY"]

    with test_app.app_context():
        db.create_all()
        assert db.session.execute(text("SELECT 1")).scalar_one() == 1


def test_index(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b"Prints On Demand" in response.data
    assert b"Your campus printing desk" in response.data
    assert b"Find a printing shop, prepare your file" in response.data
    assert b"Create student account" in response.data


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_missing_page(client):
    response = client.get("/missing")

    assert response.status_code == 404
    assert b"Page not found." in response.data


def test_production_requires_configuration(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="PostgreSQL DATABASE_URL"):
        create_app(ProductionConfig)


def test_testing_environment_switch(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    app = create_app()

    assert app.testing is True
    assert app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite://"


def test_legacy_postgres_url_is_normalized(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://user:password@localhost:5432/prints")
    monkeypatch.setenv("SECRET_KEY", "test-only-secret")

    app = create_app(ProductionConfig)

    assert app.config["SQLALCHEMY_DATABASE_URI"] == (
        "postgresql://user:password@localhost:5432/prints"
    )
    assert app.config["SESSION_COOKIE_SECURE"] is True
