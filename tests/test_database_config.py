"""Driver selection and deployment configuration without opening a remote DB."""

import pytest
from flask import Flask
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from app import create_app
from app.config import Config, ProductionConfig, TestingConfig, configure_runtime, select_config
from app.database_config import configure_database, normalize_database_url
from app.extensions import db


@pytest.fixture(autouse=True)
def isolated_database_environment(monkeypatch):
    for name in ("DATABASE_URL", "DATABASE_POOL_MODE", "VERCEL", "FLASK_ENV", "TESTING"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+psycopg"])
def test_provider_urls_use_installed_driver_without_changing_credentials(scheme):
    suffix = "user:p%40ss%2Fword@db.example:5432/prints?sslmode=verify-full&channel_binding=require"
    normalized = normalize_database_url(f"{scheme}://{suffix}")
    assert normalized == f"postgresql+psycopg://{suffix}"
    parsed = make_url(normalized)
    assert parsed.password == "p@ss/word"
    assert parsed.query == {"sslmode": "verify-full", "channel_binding": "require"}


def test_invalid_url_error_does_not_disclose_credentials():
    secret_url = "postgresql://user:private-password@db.example:bad-port/prints"
    with pytest.raises(RuntimeError) as error:
        normalize_database_url(secret_url)
    assert "private-password" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True


def test_vercel_defaults_to_production_and_refuses_testing(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    assert select_config() is ProductionConfig
    monkeypatch.setenv("TESTING", "true")
    with pytest.raises(ValueError, match="TESTING cannot be enabled"):
        select_config()


def test_vercel_rejects_an_explicit_development_profile(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    app = Flask(__name__)
    app.config.from_object(Config)
    with pytest.raises(RuntimeError, match="Vercel requires the production configuration"):
        configure_runtime(app)


def test_vercel_cannot_fall_back_to_a_local_database(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    app = Flask(__name__)
    app.config.from_object(ProductionConfig)
    with pytest.raises(RuntimeError, match="PostgreSQL DATABASE_URL"):
        configure_runtime(app)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///prints.db")
    with pytest.raises(RuntimeError, match="PostgreSQL DATABASE_URL"):
        configure_runtime(app)


def test_vercel_builds_psycopg_engine_with_external_pool_and_tls(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://pod_web:fake@ep-example-pooler.neon.tech/neondb")
    monkeypatch.setenv("SECRET_KEY", "test-production-secret-at-least-32-characters")
    monkeypatch.setenv("TRUSTED_HOSTS", "prints.example")
    monkeypatch.setenv("FORCE_HTTPS", "true")
    monkeypatch.setenv("FLASK_DEBUG", "0")
    app = create_app(ProductionConfig)
    with app.app_context():
        assert db.engine.dialect.driver == "psycopg"
        assert isinstance(db.engine.pool, NullPool)
        assert app.debug is False
        assert app.config["SESSION_COOKIE_SECURE"] is True
        args = app.config["SQLALCHEMY_ENGINE_OPTIONS"]["connect_args"]
        assert args["sslmode"] == "require"
        assert args["connect_timeout"] == 10
        assert args["prepare_threshold"] is None
        # Engine creation itself must not connect or run migrations.
        db.engine.dispose()


@pytest.mark.parametrize("sslmode", ["disable", "allow", "prefer"])
def test_vercel_rejects_a_database_url_that_can_use_plaintext(monkeypatch, sslmode):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("DATABASE_URL", f"postgresql://user:fake@db.example/prints?sslmode={sslmode}")
    app = Flask(__name__)
    app.config.from_object(ProductionConfig)
    with pytest.raises(RuntimeError, match="require TLS"):
        configure_database(app)


def test_external_pool_preserves_driver_options_and_removes_queue_arguments(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:fake@db.example/prints")
    monkeypatch.setenv("DATABASE_POOL_MODE", "null")
    app = Flask(__name__)
    app.config.from_object(TestingConfig)
    original = {"pool_size": 5, "max_overflow": 3, "pool_timeout": 30,
                "pool_use_lifo": True, "connect_args": {"application_name": "prints"}}
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = original
    configure_database(app)
    options = app.config["SQLALCHEMY_ENGINE_OPTIONS"]
    assert options["poolclass"] is NullPool
    assert not {"pool_size", "max_overflow", "pool_timeout", "pool_use_lifo"} & options.keys()
    assert options["connect_args"]["application_name"] == "prints"
    assert options["connect_args"]["prepare_threshold"] is None
    assert original == {"pool_size": 5, "max_overflow": 3, "pool_timeout": 30,
                        "pool_use_lifo": True, "connect_args": {"application_name": "prints"}}


def test_local_sqlite_does_not_receive_postgresql_connection_arguments():
    app = Flask(__name__)
    app.config.from_object(TestingConfig)
    configure_database(app)
    assert app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite://"
    assert "SQLALCHEMY_ENGINE_OPTIONS" not in app.config


def test_invalid_pool_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("DATABASE_POOL_MODE", "invalid")
    app = Flask(__name__)
    app.config.from_object(TestingConfig)
    with pytest.raises(ValueError, match="DATABASE_POOL_MODE"):
        configure_database(app)
