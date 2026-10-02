"""Shared isolated test application."""

import pytest

from app import create_app
from app.config import TestingConfig


@pytest.fixture
def test_app(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    return create_app(TestingConfig)


@pytest.fixture
def client(test_app):
    return test_app.test_client()
