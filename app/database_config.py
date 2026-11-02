"""Driver selection and connection settings for supported SQL databases."""

import os

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.pool import NullPool


def normalize_database_url(value):
    """Use the installed psycopg 3 driver without changing URL credentials."""
    if not value:
        return value
    if isinstance(value, str):
        value = value.strip()
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                value = "postgresql+psycopg://" + value[len(prefix):]
                break
    try:
        make_url(value)
    except (ArgumentError, ValueError):
        # Parser errors may include the URL, including its password.
        raise RuntimeError("DATABASE_URL must be a valid SQLAlchemy database URL.") from None
    return value


def configure_database(app):
    """Configure the database driver and an optional external connection pool."""
    value = normalize_database_url(
        os.getenv("DATABASE_URL") or app.config.get("SQLALCHEMY_DATABASE_URI")
    )
    url = make_url(value) if value else None
    if app.config["ENV_NAME"] == "production":
        if url is None or url.get_backend_name() != "postgresql":
            raise RuntimeError("Production requires a PostgreSQL DATABASE_URL.")

    mode = (os.getenv("DATABASE_POOL_MODE") or "queue").strip().lower()
    if mode not in {"null", "queue"}:
        raise ValueError("DATABASE_POOL_MODE must be null or queue.")

    if url is not None and url.get_backend_name() == "postgresql":
        options = dict(app.config.get("SQLALCHEMY_ENGINE_OPTIONS") or {})
        connect_args = dict(options.get("connect_args") or {})
        connect_args.setdefault("connect_timeout", 10)
        options.setdefault("pool_pre_ping", True)
        if app.config["ENV_NAME"] == "production":
            sslmode = url.query.get("sslmode", connect_args.get("sslmode", "require"))
            if sslmode not in {"require", "verify-ca", "verify-full"}:
                raise RuntimeError("Production database connections require TLS (sslmode=require or verify-full).")
            connect_args["sslmode"] = sslmode
        if mode == "null":
            options["poolclass"] = NullPool
            # QueuePool arguments are not accepted by NullPool.
            for name in ("pool_size", "max_overflow", "pool_timeout", "pool_use_lifo"):
                options.pop(name, None)
            if url.drivername == "postgresql+psycopg":
                connect_args["prepare_threshold"] = None
        options["connect_args"] = connect_args
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = options
    elif mode == "null":
        raise RuntimeError("DATABASE_POOL_MODE=null requires PostgreSQL.")

    app.config["SQLALCHEMY_DATABASE_URI"] = value
