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
    UPLOAD_MAX_SIZE = 25 * 1024 * 1024
    UPLOAD_MAX_QUANTITY = 999
    UPLOAD_STORAGE_ROOT = None
    STORAGE_BACKEND = "local"
    ORDER_CURRENCY = "PHP"
    ORDER_MAX_FILES = 20
    CHECKOUT_STAGED_RETENTION_HOURS = 24
    FULFILLMENT_TIMEZONE = "Asia/Manila"
    PICKUP_LEAD_DAYS = 0
    PICKUP_MAX_DAYS = 30
    DELIVERY_LEAD_DAYS = 0
    DELIVERY_MAX_DAYS = 30
    ONLINE_PAYMENT_ENABLED = False
    ONLINE_PAYMENT_INSTRUCTIONS = ""
    ONLINE_PAYMENT_ACCOUNT_NAME = ""
    ONLINE_PAYMENT_DESTINATION = ""
    PAYMENT_QR_IMAGE_URL = ""
    ONSITE_PAYMENT_INSTRUCTIONS = "Pay at the printing shop. Your order remains unpaid until payment is recorded."
    GOOGLE_MAPS_API_KEY = ""
    GOOGLE_MAPS_MAP_ID = "DEMO_MAP_ID"


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///prints_on_demand.db"


class TestingConfig(Config):
    ENV_NAME = "testing"
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"


class ProductionConfig(Config):
    ENV_NAME = "production"
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    GOOGLE_MAPS_MAP_ID = ""


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
        secret_key = os.getenv("SECRET_KEY", "")
        if len(secret_key.strip()) < 32:
            raise RuntimeError("Production requires a SECRET_KEY of at least 32 characters.")
        flask_debug = os.getenv("FLASK_DEBUG")
        # Match Flask CLI's parsing: values such as "off" or " false" enable debug.
        debug_enabled = bool(flask_debug and flask_debug.lower() not in {"0", "false", "no"})
        if app.config.get("DEBUG") or debug_enabled:
            raise RuntimeError("Debug mode must be disabled in production.")

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SECRET_KEY"] = (
        os.getenv("SECRET_KEY")
        or app.config.get("SECRET_KEY")
        or secrets.token_urlsafe(32)
    )
    for name in ("UPLOAD_MAX_SIZE", "UPLOAD_MAX_QUANTITY"):
        value = os.getenv(name)
        if value:
            try:
                parsed = int(value)
            except ValueError as error:
                raise ValueError(f"{name} must be a positive integer.") from error
            if parsed < 1:
                raise ValueError(f"{name} must be a positive integer.")
            app.config[name] = parsed
    # Deployment overrides may lower the file limit, but never exceed 25 MiB.
    app.config["UPLOAD_MAX_SIZE"] = min(app.config["UPLOAD_MAX_SIZE"], 25 * 1024 * 1024)
    app.config["UPLOAD_STORAGE_ROOT"] = (
        os.getenv("UPLOAD_STORAGE_ROOT") or app.config.get("UPLOAD_STORAGE_ROOT")
        or os.path.join(app.instance_path, "uploads")
    )
    app.config["STORAGE_BACKEND"] = os.getenv("STORAGE_BACKEND") or app.config["STORAGE_BACKEND"]
    app.config["GOOGLE_MAPS_API_KEY"] = (os.getenv("GOOGLE_MAPS_API_KEY") or "").strip()
    app.config["GOOGLE_MAPS_MAP_ID"] = (
        os.getenv("GOOGLE_MAPS_MAP_ID") or app.config["GOOGLE_MAPS_MAP_ID"]
    ).strip()
    online_enabled = os.getenv("ONLINE_PAYMENT_ENABLED")
    if online_enabled:
        normalized = online_enabled.strip().lower()
        if normalized not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
            raise ValueError("ONLINE_PAYMENT_ENABLED must be a boolean value.")
        app.config["ONLINE_PAYMENT_ENABLED"] = normalized in {"true", "1", "yes", "on"}
    for name in (
        "ONLINE_PAYMENT_INSTRUCTIONS", "ONLINE_PAYMENT_ACCOUNT_NAME",
        "ONLINE_PAYMENT_DESTINATION", "ONSITE_PAYMENT_INSTRUCTIONS",
        "PAYMENT_QR_IMAGE_URL",
    ):
        value = os.getenv(name)
        if value:
            app.config[name] = value.strip()
    # Allow room for multipart headers while enforcing the file's own limit separately.
    app.config["MAX_CONTENT_LENGTH"] = app.config["UPLOAD_MAX_SIZE"] + 64 * 1024
