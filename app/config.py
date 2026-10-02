"""Environment-aware application configuration."""

import os
import secrets
from datetime import timedelta

from flask import Flask


class Config:
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)
    REMEMBER_COOKIE_DURATION = timedelta(days=14)
    ENV_NAME = "development"


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///prints_on_demand.db"


class TestingConfig(Config):
    ENV_NAME = "testing"
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"


class ProductionConfig(Config):
    ENV_NAME = "production"
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True


CONFIGS = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def select_config() -> type[Config]:
    """Select the environment; default to local development."""
    name = (os.getenv("FLASK_ENV") or "development").strip().lower()
    testing = (os.getenv("TESTING") or "").strip().lower()
    if testing and testing not in {"1", "true", "yes", "on", "0", "false", "no", "off"}:
        raise ValueError("TESTING must be a boolean value.")
    if testing in {"1", "true", "yes", "on"}:
        if name == "production":
            raise ValueError("TESTING cannot be enabled in production.")
        name = "testing"
    try:
        return CONFIGS[name]
    except KeyError as error:
        raise ValueError(f"Unsupported FLASK_ENV: {name!r}") from error


def configure_runtime(app: Flask) -> None:
    """Apply environment overrides and require production secrets/config."""
    database_url = os.getenv("DATABASE_URL") or app.config.get("SQLALCHEMY_DATABASE_URI")
    if database_url and database_url.startswith("postgres://"):
        database_url = "postgresql://" + database_url[len("postgres://") :]

    if app.config["ENV_NAME"] == "production":
        if not database_url or not database_url.startswith("postgresql"):
            raise RuntimeError("Production requires a PostgreSQL DATABASE_URL.")
        if not os.getenv("SECRET_KEY"):
            raise RuntimeError("Production requires SECRET_KEY.")

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SECRET_KEY"] = (
        os.getenv("SECRET_KEY")
        or app.config.get("SECRET_KEY")
        or secrets.token_urlsafe(32)
    )
