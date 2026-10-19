"""Adversarial checks for revoked credentials, expiry, transport and abuse."""

import hashlib
import io
import re
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from contextlib import closing

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import AuthSession, RateLimitBucket, User
from app.services.backups import BackupError, snapshot_database, verify_archive, write_archive
from app.services.sessions import now_seconds
from test_auth import add_user, csrf_token, login, register
from test_orders import file, sign_in, student


def login_remembered(client):
    token = csrf_token(client.get("/auth/login"))
    return client.post("/auth/login", data={"email": "student@example.com",
        "password": "A-strong-password-123", "remember_me": "y", "csrf_token": token})


def test_logout_revokes_copied_session_and_remember_cookies(client, test_app):
    add_user(test_app)
    assert login_remembered(client).status_code == 302
    copied_session = client.get_cookie("session").value
    copied_remember = client.get_cookie("remember_token").value
    attacker = test_app.test_client()
    attacker.set_cookie("session", copied_session)
    assert attacker.get("/student").status_code == 200
    response = client.post("/auth/logout", data={"csrf_token": csrf_token(client.get("/student"))})
    assert response.status_code == 302
    assert response.headers["Clear-Site-Data"] == '"cache", "cookies", "storage"'
    assert client.get_cookie("remember_token") is None
    attacker.set_cookie("session", copied_session)
    assert attacker.get("/student").status_code == 302
    attacker.delete_cookie("session")
    attacker.set_cookie("remember_token", copied_remember)
    assert attacker.get("/student").status_code == 302
    assert db.session.scalar(select(AuthSession)) is None


@pytest.mark.parametrize("expired", ["idle", "absolute"])
def test_server_expiry_rejects_even_validly_signed_cookies(client, test_app, expired):
    add_user(test_app)
    assert login(client).status_code == 302
    record = db.session.scalar(select(AuthSession))
    if expired == "idle":
        record.last_seen_at = now_seconds() - record.idle_seconds - 1
    else:
        record.expires_at = now_seconds() - 1
    db.session.commit()
    response = client.get("/student")
    assert response.status_code == 302
    assert response.headers["Clear-Site-Data"] == '"cache", "storage"'
    assert db.session.scalar(select(AuthSession)) is None
    # Expiry clears stale browser storage without deleting the new login-form
    # CSRF cookie. A fresh login must remain usable after the redirect.
    assert login(client).status_code == 302


def test_session_rotation_and_password_change_invalidation(client, test_app):
    user_id = add_user(test_app)
    with client.session_transaction() as state:
        state["checkout_draft"] = {"shop_id": 999}
        state["untrusted"] = "anonymous-state"
    assert login(client).status_code == 302
    with client.session_transaction() as state:
        token = state["_user_id"]
        assert token != str(user_id)
        assert "untrusted" not in state and "checkout_draft" not in state
    record = db.session.scalar(select(AuthSession))
    assert record.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert record.token_hash != token
    db.session.get(User, user_id).set_password("Changed-password-12345")
    db.session.commit()
    assert client.get("/student").status_code == 302


def test_remember_login_has_fixed_upper_bound_and_server_idle_expiry(client, test_app):
    add_user(test_app)
    assert login_remembered(client).status_code == 302
    record = db.session.scalar(select(AuthSession))
    assert record.expires_at - record.created_at == 14 * 86400
    assert record.idle_seconds == 7 * 86400
    original_expiry = record.expires_at
    client.delete_cookie("session")
    assert client.get("/student").status_code == 200
    assert db.session.scalar(select(AuthSession)).expires_at == original_expiry


def test_legacy_identity_cookie_is_not_an_authentication_credential(client, test_app):
    user_id = add_user(test_app)
    with client.session_transaction() as state:
        state["_user_id"] = str(user_id)
    assert client.get("/student").status_code == 302


def test_login_limit_shared_across_clients_and_public_login_forms(client, test_app):
    test_app.config["AUTH_RATE_LIMIT"] = 2
    for path in ("/auth/login", "/auth/shop-login"):
        # Invalid CSRF cannot bypass the IP bucket.
        assert test_app.test_client().post(path, data={}).status_code == 400
    response = client.post("/auth/login?blue=1", data={})
    assert response.status_code == 429
    assert 0 < int(response.headers["Retry-After"]) <= 900
    assert "no-store" in response.headers["Cache-Control"]
    keys = db.session.scalars(select(RateLimitBucket.key)).all()
    assert keys and all("127.0.0.1" not in key and len(key) == 64 for key in keys)


def test_identifier_limit_applies_across_ip_addresses(client, test_app):
    test_app.config["AUTH_IDENTIFIER_RATE_LIMIT"] = 1
    first = client.post("/auth/login", data={"email": "Target@Example.edu"},
                        environ_overrides={"REMOTE_ADDR": "192.0.2.1"})
    assert first.status_code == 400
    second = client.post("/auth/login", data={"email": " target@example.edu "},
                         environ_overrides={"REMOTE_ADDR": "192.0.2.2"})
    assert second.status_code == 429


def test_signup_limit_prevents_account_creation(client, test_app):
    test_app.config["REGISTRATION_RATE_LIMIT"] = 1
    assert register(client).status_code == 302
    assert register(client, email="second@example.edu").status_code == 429
    assert len(db.session.scalars(select(User)).all()) == 1


def test_https_redirects_get_and_rejects_insecure_posts(client, test_app):
    test_app.config["FORCE_HTTPS"] = True
    response = client.get("/auth/login?next=/orders")
    assert response.status_code == 308
    assert response.headers["Location"].startswith("https://localhost/auth/login?")
    assert client.post("/auth/login", data={}).status_code == 400
    secure = client.get("/auth/login", base_url="https://localhost")
    assert secure.status_code == 200
    assert secure.headers["Strict-Transport-Security"] == "max-age=31536000"
    # Untrusted forwarded headers do not bypass the transport requirement.
    assert client.get("/auth/login", headers={"X-Forwarded-Proto": "https"}).status_code == 308


def test_private_responses_and_download_errors_cannot_be_cached(client, test_app):
    sign_in(client, student(test_app))
    for path in ("/student", "/orders", "/account", "/files/999/download"):
        response = client.get(path)
        assert "no-store" in response.headers["Cache-Control"]
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_form_memory_bound_does_not_shrink_25_mib_file_capacity(client, test_app):
    sign_in(client, student(test_app))
    limit = 25 * 1024 * 1024
    # Transport boundary check using the existing signature-screened PNG format.
    payload = b"\x89PNG\r\n\x1a\n" + b"x" * (limit - 8)
    token = csrf_token(client.get("/checkout/upload"))
    accepted = client.post("/checkout/upload/files", data={
        "csrf_token": token, "files": (io.BytesIO(payload), "capacity.png", "image/png"),
    }, content_type="multipart/form-data")
    assert accepted.status_code == 302
    rejected = client.post("/checkout/upload/files", data={
        "csrf_token": csrf_token(client.get("/checkout/upload")),
        "files": (io.BytesIO(payload + b"x"), "too-large.png", "image/png"),
    }, content_type="multipart/form-data")
    assert rejected.status_code == 413


def test_every_mutating_route_rejects_missing_csrf(client, test_app):
    for rule in test_app.url_map.iter_rules():
        if "POST" not in rule.methods:
            continue
        path = re.sub(r"<[^>]+>", "1", rule.rule)
        response = client.post(path, data={})
        assert response.status_code == 400, (rule.endpoint, response.status_code)


def test_only_configured_proxy_headers_are_trusted(monkeypatch):
    from app import create_app
    from app.config import TestingConfig
    class ProxiedConfig(TestingConfig):
        FORCE_HTTPS = True
        PROXY_FIX_HOPS = 1
        TRUSTED_HOSTS = ["prints.example"]
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PROXY_FIX_HOPS", raising=False)
    monkeypatch.delenv("FORCE_HTTPS", raising=False)
    app = create_app(ProxiedConfig)
    client = app.test_client()
    secure = client.get("/", base_url="http://prints.example", headers={"X-Forwarded-Proto": "https"})
    assert secure.status_code == 200
    assert "Strict-Transport-Security" in secure.headers
    assert client.get("/", base_url="https://attacker.example").status_code == 400
    # Trusting proto/IP does not grant a forwarded host control of redirects.
    redirected = client.get("/", base_url="http://prints.example", headers={"X-Forwarded-Host": "attacker.example"})
    assert redirected.headers["Location"] == "https://prints.example/"


def test_production_requires_host_allowlist_and_https(monkeypatch):
    from app import create_app
    from app.config import ProductionConfig
    monkeypatch.setenv("DATABASE_URL", "postgresql://runtime:placeholder@localhost/prints")
    monkeypatch.setenv("SECRET_KEY", "qa-signing-key-that-is-long-enough-1234")
    monkeypatch.delenv("TRUSTED_HOSTS", raising=False)
    with pytest.raises(RuntimeError, match="TRUSTED_HOSTS"):
        create_app(ProductionConfig)
    monkeypatch.setenv("TRUSTED_HOSTS", "prints.example")
    monkeypatch.setenv("FORCE_HTTPS", "false")
    with pytest.raises(RuntimeError, match="HTTPS enforcement"):
        create_app(ProductionConfig)


def test_snapshot_and_document_backup_can_be_verified_and_restored(test_app, tmp_path):
    user_id = student(test_app)
    file(test_app, user_id)
    snapshot, records = snapshot_database(tmp_path)
    archive = tmp_path / "snapshot.tar.gz"
    write_archive(archive, snapshot, records)
    assert verify_archive(archive) == 1
    # Restore the DB into a separate file; do not touch the application database.
    with tarfile.open(archive, "r:gz") as bundle:
        restored = tmp_path / "restored.sqlite3"
        restored.write_bytes(bundle.extractfile("database.sqlite3").read())
        with closing(sqlite3.connect(restored)) as connection:
            assert connection.execute("SELECT email FROM users").fetchone()[0] == "student@example.com"
            key, checksum = connection.execute("SELECT storage_key, sha256 FROM uploaded_files").fetchone()
        assert hashlib.sha256(bundle.extractfile(f"uploads/{key}").read()).hexdigest() == checksum


def test_backup_rejects_missing_or_corrupted_private_documents(test_app, tmp_path):
    user_id = student(test_app)
    file(test_app, user_id)
    snapshot, records = snapshot_database(tmp_path)
    key = records[0][0]
    from pathlib import Path
    (Path(test_app.config["UPLOAD_STORAGE_ROOT"]) / key).write_bytes(b"corrupt")
    with pytest.raises(BackupError):
        write_archive(tmp_path / "bad.tar.gz", snapshot, records)


@pytest.mark.skipif(not shutil.which("gpg"), reason="GnuPG is optional external backup tooling")
def test_encrypted_backup_and_recovery_verification(test_app, tmp_path, monkeypatch):
    from pathlib import Path
    # GnuPG agents use Unix-domain sockets with short pathname limits.
    key_directory = tempfile.TemporaryDirectory(prefix="podb-")
    home = Path(key_directory.name)
    home.chmod(0o700)
    from app.services.backups import gpg_filename
    monkeypatch.setenv("GNUPGHOME", gpg_filename(home))
    key = subprocess.run([
        "gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase", "",
        "--quick-generate-key", "Backup QA <backup@example.invalid>", "rsa2048", "encr", "1d",
    ], capture_output=True, timeout=60)
    assert key.returncode == 0, key.stderr.decode(errors="replace")
    listing = subprocess.run(["gpg", "--batch", "--with-colons", "--list-keys"],
                             capture_output=True, text=True, check=True)
    fingerprint = next(line.split(":")[9] for line in listing.stdout.splitlines() if line.startswith("fpr:"))
    monkeypatch.setenv("BACKUP_GPG_RECIPIENT", fingerprint)
    destination = tmp_path / "encrypted"
    monkeypatch.setenv("BACKUP_DIRECTORY", str(destination))
    file(test_app, student(test_app))
    runner = test_app.test_cli_runner()
    created = runner.invoke(args=["backup-data"])
    assert created.exit_code == 0, created.output
    encrypted = list(destination.glob("*.gpg"))
    assert len(encrypted) == 1 and not list(destination.glob(".backup-*"))
    assert b"student@example.com" not in encrypted[0].read_bytes()
    verified = runner.invoke(args=["verify-backup", str(encrypted[0])])
    assert verified.exit_code == 0 and "database and 1 private documents" in verified.output
    damaged = bytearray(encrypted[0].read_bytes())
    damaged[len(damaged) // 2] ^= 1
    encrypted[0].write_bytes(damaged)
    assert runner.invoke(args=["verify-backup", str(encrypted[0])]).exit_code != 0
    # Shut down the isolated GnuPG agent before pytest removes its key directory.
    if shutil.which("gpgconf"):
        subprocess.run(["gpgconf", "--kill", "gpg-agent"], capture_output=True)
    key_directory.cleanup()


def test_cleanup_removes_only_expired_security_records(client, test_app):
    add_user(test_app)
    login(client)
    live = db.session.scalar(select(AuthSession))
    db.session.add(RateLimitBucket(key="0" * 64, count=1, expires_at=now_seconds() - 1))
    db.session.commit()
    result = test_app.test_cli_runner().invoke(args=["cleanup-security-state"])
    assert result.exit_code == 0
    assert db.session.get(AuthSession, live.token_hash) is not None
    assert db.session.get(RateLimitBucket, "0" * 64) is None


def test_deployment_check_reports_gaps_without_exposing_credentials(test_app):
    add_user(test_app)
    result = test_app.test_cli_runner().invoke(args=["security-check"])
    assert result.exit_code != 0
    assert "FAIL HTTPS enforced" in result.output
    assert "FAIL Encrypted backup created within 36 hours" in result.output
    assert "PASS Password hashes use supported algorithms" in result.output
    assert "A-strong-password-123" not in result.output
    assert "student@example.com" not in result.output
    assert len(db.session.scalars(select(User)).all()) == 1
