"""Encrypted, verifiable snapshots of the database and private documents."""

import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from contextlib import closing
from datetime import datetime, timezone

from flask import current_app
from sqlalchemy import select, text

from app.extensions import db
from app.models import UploadedFile
from app.storage import get_account_deletion_storage


class BackupError(ValueError):
    pass


def gpg_filename(path):
    """Git for Windows bundles an MSYS GPG that expects POSIX file paths."""
    resolved = Path(path).resolve()
    executable = (shutil.which("gpg") or "").replace("\\", "/").lower()
    if os.name == "nt" and "/git/usr/bin/" in executable:
        return f"/{resolved.drive[0].lower()}{resolved.as_posix()[2:]}"
    return str(resolved)


def file_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_database(directory):
    """Return a consistent DB snapshot and its referenced immutable uploads."""
    if db.engine.dialect.name == "sqlite":
        path = directory / "database.sqlite3"
        with path.open("xb"):
            pass
        path.chmod(0o600)
        source = db.engine.raw_connection()
        try:
            with closing(sqlite3.connect(path)) as destination:
                source.driver_connection.backup(destination)
                if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise BackupError("Database integrity check failed.")
                records = destination.execute(
                    "SELECT storage_key, file_size, sha256 FROM uploaded_files"
                ).fetchall()
        finally:
            source.close()
        return path, records
    if db.engine.dialect.name != "postgresql" or not shutil.which("pg_dump"):
        raise BackupError("PostgreSQL backup requires pg_dump matching the server version.")
    path = directory / "database.dump"
    url = db.engine.url
    environment = dict(os.environ)
    environment["PGPASSWORD"] = url.password or ""
    if url.query.get("sslmode"):
        environment["PGSSLMODE"] = url.query["sslmode"]
    with db.engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with connection.begin():
            snapshot = connection.execute(text("SELECT pg_export_snapshot()")).scalar_one()
            records = connection.execute(select(
                UploadedFile.storage_key, UploadedFile.file_size, UploadedFile.sha256
            )).all()
            result = subprocess.run([
                "pg_dump", "--no-password", "--format=custom", f"--snapshot={snapshot}",
                f"--host={url.host or 'localhost'}", f"--port={url.port or 5432}",
                f"--username={url.username or ''}", f"--dbname={url.database or ''}",
                f"--file={path}",
            ], env=environment, capture_output=True, timeout=1800)
            if result.returncode:
                raise BackupError("Database snapshot failed. Check pg_dump access and version.")
    path.chmod(0o600)
    return path, records


def write_archive(path, snapshot, records):
    """Abort if a referenced file disappears or its recorded hash differs."""
    storage = get_account_deletion_storage()
    manifest = {"version": 1, "created_at": datetime.now(timezone.utc).isoformat(), "files": {}}
    with tarfile.open(path, "w:gz") as archive:
        for source, name, expected_size, expected_hash in [
            (snapshot, snapshot.name, snapshot.stat().st_size, file_digest(snapshot)),
            *[(storage._path(key), f"uploads/{key}", size, checksum) for key, size, checksum in records],
        ]:
            # Stream the exact bytes checked into the archive, avoiding a second read.
            digest = hashlib.sha256()
            with source.open("rb") as stream:
                size = os.fstat(stream.fileno()).st_size
                if size != expected_size:
                    raise BackupError("A snapshot document has a size mismatch.")
                class HashingReader:
                    def read(self, amount):
                        chunk = stream.read(amount)
                        digest.update(chunk)
                        return chunk
                entry = tarfile.TarInfo(name)
                entry.size, entry.mode = size, 0o600
                archive.addfile(entry, HashingReader())
            if digest.hexdigest() != expected_hash:
                raise BackupError("A snapshot document failed its integrity check.")
            manifest["files"][name] = {"size": size, "sha256": digest.hexdigest()}
        payload = json.dumps(manifest, sort_keys=True).encode()
        entry = tarfile.TarInfo("manifest.json")
        entry.size, entry.mode = len(payload), 0o600
        archive.addfile(entry, io.BytesIO(payload))
    path.chmod(0o600)


def verify_archive(path):
    """Verify every byte and filename without extracting potentially unsafe paths."""
    actual, manifest, seen = {}, None, set()
    with tarfile.open(path, "r:gz") as archive:
        for entry in archive:
            if not entry.isfile() or entry.name in seen:
                raise BackupError("Invalid or duplicate archive entry.")
            seen.add(entry.name)
            stream = archive.extractfile(entry)
            if entry.name == "manifest.json":
                if manifest is not None or entry.size > 1024 * 1024:
                    raise BackupError("Invalid backup manifest.")
                manifest = json.load(stream)
                continue
            if not re.fullmatch(r"database\.(?:sqlite3|dump)|uploads/[0-9a-f]{32}\.[a-z0-9]+", entry.name):
                raise BackupError("Unexpected archive entry.")
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
            actual[entry.name] = {"size": entry.size, "sha256": digest.hexdigest()}
    if (not isinstance(manifest, dict) or manifest.get("version") != 1 or manifest.get("files") != actual
            or len([name for name in actual if name.startswith("database.")]) != 1):
        raise BackupError("Backup manifest or file integrity check failed.")
    return len(actual) - 1


def create_backup():
    recipient = os.getenv("BACKUP_GPG_RECIPIENT", "").strip()
    root_value = os.getenv("BACKUP_DIRECTORY", "").strip()
    if not root_value or not re.fullmatch(r"[A-Fa-f0-9]{40,64}", recipient) or not shutil.which("gpg"):
        raise BackupError("Set BACKUP_DIRECTORY and a full BACKUP_GPG_RECIPIENT fingerprint; install gpg first.")
    root = Path(root_value).resolve()
    public = Path(current_app.static_folder).resolve()
    uploads = Path(current_app.config["UPLOAD_STORAGE_ROOT"]).resolve()
    if root == public or public in root.parents or root == uploads or uploads in root.parents:
        raise BackupError("Backup storage must be outside public and upload directories.")
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    root.chmod(0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = root / f"prints-backup-{stamp}.tar.gz.gpg"
    pending = root / f".{target.name}.partial"
    try:
        with tempfile.TemporaryDirectory(prefix=".backup-", dir=root) as temporary:
            directory = Path(temporary)
            directory.chmod(0o700)
            snapshot, records = snapshot_database(directory)
            archive = directory / "snapshot.tar.gz"
            write_archive(archive, snapshot, records)
            verify_archive(archive)
            encrypted = directory / "snapshot.gpg"
            result = subprocess.run([
                "gpg", "--batch", "--no-tty", "--trust-model", "always", "--compress-algo", "none",
                "--recipient", recipient, "--output", gpg_filename(encrypted), "--encrypt", gpg_filename(archive),
            ], capture_output=True, timeout=1800)
            if result.returncode or not encrypted.is_file():
                raise BackupError("Backup encryption failed. Check the recipient public key.")
            encrypted.chmod(0o600)
            encrypted.replace(pending)
        # Publish only after the plaintext temporary files have been removed.
        pending.replace(target)
    except Exception:
        pending.unlink(missing_ok=True)
        raise
    return target
