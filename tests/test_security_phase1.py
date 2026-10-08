"""Regressions for abuse controls and uploaded-content validation."""

import io
import zipfile

import pytest
from sqlalchemy import select
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import TooManyRequests

from app.extensions import db
from app.models.rate_limit import RateLimitBucket
from app.security_limits import enforce_limit
from app.storage.validation import UploadValidationError, validate_upload
from test_auth import PASSWORD, add_user, csrf_token


def test_login_attempts_are_throttled_without_exposing_account(client, test_app):
    add_user(test_app)
    token = csrf_token(client.get("/auth/login"))
    for _ in range(10):
        response = client.post("/auth/login", data={
            "csrf_token": token, "email": "student@example.com", "password": "incorrect",
        })
        assert response.status_code == 200
        assert b"Invalid email or password" in response.data
    blocked = client.post("/auth/login", data={
        "csrf_token": token, "email": "student@example.com", "password": PASSWORD,
    })
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    assert blocked.headers["Cache-Control"] == "private, no-store"
    assert client.get("/student").status_code == 302


def test_private_pages_disable_browser_caching_and_unused_device_permissions(client, test_app):
    add_user(test_app)
    token = csrf_token(client.get("/auth/login"))
    assert client.post("/auth/login", data={
        "csrf_token": token, "email": "student@example.com", "password": PASSWORD,
    }).status_code == 302
    response = client.get("/student")
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Permissions-Policy"] == "camera=(), microphone=()"
    test_app.config["ENV_NAME"] = "production"
    assert client.get("/student").headers["Strict-Transport-Security"] == "max-age=31536000"


def test_rate_counters_are_shared_and_hide_raw_identity(test_app):
    with test_app.test_request_context("/"):
        enforce_limit("security-test", "private@example.com", attempts=2, seconds=900)
        enforce_limit("security-test", "private@example.com", attempts=2, seconds=900)
        with pytest.raises(TooManyRequests):
            enforce_limit("security-test", "private@example.com", attempts=2, seconds=900)
        bucket = db.session.scalar(select(RateLimitBucket))
        assert len(bucket.key) == 64
        assert "private" not in bucket.key
        assert bucket.hits == 2


def test_fake_image_headers_are_rejected():
    for name, content, mime in (
        ("fake.jpg", b"\xff\xd8\xffphoto\xff\xd9", "image/jpeg"),
        ("fake.png", b"\x89PNG\r\n\x1a\nimage", "image/png"),
    ):
        upload = FileStorage(stream=io.BytesIO(content), filename=name, content_type=mime)
        try:
            validate_upload(upload, 1024)
        except UploadValidationError as error:
            assert "content does not match" in str(error)
        else:
            raise AssertionError("Invalid image was accepted")


def test_oversized_or_unsafe_office_archive_is_rejected():
    for unsafe_name in ("../outside.xml", "C:/outside.xml", "word/part.xml"):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", (
                '<Types><Override ContentType="application/vnd.openxmlformats-officedocument.'
                'wordprocessingml.document.main+xml"/></Types>'
            ))
            archive.writestr("word/document.xml", "<document/>")
            archive.writestr(unsafe_name, b"x" * (65 * 1024 * 1024) if unsafe_name.startswith("word/") else b"x")
        upload = FileStorage(stream=io.BytesIO(output.getvalue()), filename="notes.docx",
                             content_type="application/octet-stream")
        try:
            validate_upload(upload, 16 * 1024 * 1024)
        except UploadValidationError as error:
            assert "content does not match" in str(error)
        else:
            raise AssertionError("Unsafe Office archive was accepted")
