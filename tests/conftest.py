"""Shared isolated test application."""

import pytest

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
    app.config["UPLOAD_MAX_SIZE"] = 16 * 1024 * 1024
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
