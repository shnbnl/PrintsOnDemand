"""Shared isolated test application."""

import pytest
from flask import g
from datetime import datetime
from zoneinfo import ZoneInfo

from app import create_app
from app.config import TestingConfig
from app.extensions import db


@pytest.fixture(autouse=True)
def isolate_word_converter_setting(monkeypatch):
    """Keep local .env renderer paths from changing test expectations."""
    monkeypatch.setenv("WORD_CONVERTER_PATH", "")


@pytest.fixture
def test_app(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    app = create_app(TestingConfig)
    # Ordering tests use business hours regardless of when the suite runs.
    # Boundary tests override this clock explicitly.
    monkeypatch.setattr("app.services.shop_hours.local_now", lambda: datetime.now(
        ZoneInfo(app.config["FULFILLMENT_TIMEZONE"])
    ).replace(hour=12, minute=0, second=0, microsecond=0))
    # This fixture deliberately holds an app context across requests. Production
    # requests each receive a new g; discard its per-request caches accordingly.
    def reset_request_caches():
        g.pop("_login_user", None)
        g.pop("csrf_token", None)
        g.pop("clear_site_data", None)
        g.pop("clear_browser_cookies", None)
        g.pop("database_actor_id", None)
        g.pop("database_erasure_id", None)
    app.before_request_funcs.setdefault(None, []).insert(0, reset_request_caches)
    app.config["UPLOAD_MAX_SIZE"] = 25 * 1024 * 1024
    app.config["MAX_CONTENT_LENGTH"] = app.config["UPLOAD_MAX_SIZE"] + 64 * 1024
    app.config["UPLOAD_MAX_QUANTITY"] = 999
    app.config["STORAGE_BACKEND"] = "local"
    app.config["UPLOAD_STORAGE_ROOT"] = str(tmp_path / "uploads")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(test_app):
    return test_app.test_client()
