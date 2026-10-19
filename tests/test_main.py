"""Foundation behavior and configuration checks."""

import re
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
    assert b">Log in</a>" in response.data
    assert b">Sign up</a>" in response.data
    assert response.data.count(b'href="/auth/register"') == 1
    registration = client.get("/auth/register")
    choices = re.findall(rb'<input[^>]*name="account_type"[^>]*>', registration.data)
    assert len(choices) == 2 and all(b"checked" not in choice for choice in choices)
    assert b'<nav class="desktop-nav"' not in response.data
    assert b'<details class="mobile-nav"' not in response.data
    assert response.data.count(b"prints-on-demand-logo.png") >= 3
    assert b"entry-transitions.css" in response.data
    logo = client.get("/static/img/prints-on-demand-logo.png")
    assert logo.status_code == 200 and logo.mimetype == "image/png"


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_missing_page(client):
    response = client.get("/missing")

    assert response.status_code == 404
    assert b"Page not found." in response.data


@pytest.mark.parametrize("path", [
    "/shops/9223372036854775808",
    "/admin/shops/9223372036854775808/edit",
    "/admin/professors/9223372036854775808/edit",
    "/admin/staff/9223372036854775808/assignment",
    "/staff/orders/example/files/9223372036854775808/download",
])
def test_oversized_database_ids_are_rejected_by_routing(client, path):
    assert client.get(path).status_code == 404


def test_production_requires_configuration(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="PostgreSQL DATABASE_URL"):
        create_app(ProductionConfig)


@pytest.mark.parametrize("secret", ["", " ", "short-secret"])
def test_production_rejects_weak_signing_key(monkeypatch, secret):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@localhost:5432/prints")
    monkeypatch.setenv("SECRET_KEY", secret)

    with pytest.raises(RuntimeError, match="SECRET_KEY of at least 32 characters"):
        create_app(ProductionConfig)


@pytest.mark.parametrize("flask_debug", ["1", "off", " false"])
def test_production_rejects_debug_mode(monkeypatch, flask_debug):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@localhost:5432/prints")
    monkeypatch.setenv("SECRET_KEY", "test-production-key-with-adequate-length")
    monkeypatch.setenv("FLASK_DEBUG", flask_debug)

    with pytest.raises(RuntimeError, match="Debug mode must be disabled"):
        create_app(ProductionConfig)


def test_browser_security_headers(client):
    response = client.get("/")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "same-origin"


def test_testing_environment_switch(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    app = create_app()

    assert app.testing is True
    assert app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite://"


def test_legacy_postgres_url_is_normalized(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://user:password@localhost:5432/prints")
    monkeypatch.setenv("SECRET_KEY", "test-production-key-with-adequate-length")
    monkeypatch.setenv("TRUSTED_HOSTS", "prints.example")

    app = create_app(ProductionConfig)

    assert app.config["SQLALCHEMY_DATABASE_URI"] == (
        "postgresql://user:password@localhost:5432/prints"
    )
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["REMEMBER_COOKIE_SECURE"] is True
    assert app.config["REMEMBER_COOKIE_HTTPONLY"] is True
    assert app.config["DEBUG"] is False
