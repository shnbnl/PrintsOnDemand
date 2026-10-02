"""Small private-storage interface; a durable backend can replace local storage."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Protocol

from flask import current_app

from app.storage.validation import ALLOWED_EXTENSIONS


class StorageError(Exception):
    """A storage reference is missing, invalid, or unavailable."""


class StorageBackend(Protocol):
    def save(self, data: bytes, extension: str) -> str: ...
    def read(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class LocalStorage:
    def __init__(self, root: str | Path, static_folder: str | Path):
        self.root = Path(root).resolve()
        static_root = Path(static_folder).resolve()
        if self.root == static_root or static_root in self.root.parents:
            raise StorageError("Private storage cannot be inside the public static directory.")

    def _path(self, key: str) -> Path:
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{32}\.[a-z0-9]+", key):
            raise StorageError("Invalid storage reference.")
        if key.rsplit(".", 1)[1] not in ALLOWED_EXTENSIONS:
            raise StorageError("Invalid storage reference.")
        path = self.root / key
        if path.is_symlink() or path.resolve().parent != self.root:
            raise StorageError("Invalid storage reference.")
        return path

    def save(self, data: bytes, extension: str) -> str:
        if extension not in ALLOWED_EXTENSIONS:
            raise StorageError("Unsupported storage extension.")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        key = f"{uuid.uuid4().hex}.{extension}"
        path = self._path(key)
        try:
            with path.open("xb") as stream:
                stream.write(data)
        except OSError:
            path.unlink(missing_ok=True)
            raise
        return key

    def read(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError as error:
            raise StorageError("Stored file is unavailable.") from error

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            pass


def get_storage() -> StorageBackend:
    """Select the backend without binding routes to filesystem operations."""
    if current_app.config["ENV_NAME"] == "production":
        raise StorageError("Configure durable private storage before production uploads.")
    if current_app.config["STORAGE_BACKEND"] != "local":
        raise StorageError("Storage backend is unavailable.")
    return LocalStorage(current_app.config["UPLOAD_STORAGE_ROOT"], current_app.static_folder)
