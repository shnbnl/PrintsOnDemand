"""Small private-storage interface; a durable backend can replace local storage."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Callable, Protocol

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

    def stage_deletion(self, keys: list[str]) -> StagedDeletion:
        """Move exact private uploads aside until the database commits.

        The staging directory is on the same filesystem as the originals so a
        failed transaction can restore them without copying document contents.
        """
        if not keys:
            return StagedDeletion(None, [])
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory = self.root / f".account-deletion-{uuid.uuid4().hex}"
        directory.mkdir(mode=0o700)
        staged = StagedDeletion(directory, [])
        try:
            for key in keys:
                source = self._path(key)
                if not source.exists():
                    continue  # A missing upload has no remaining bytes to remove.
                if not source.is_file():
                    raise StorageError("Private upload is not a regular file.")
                destination = directory / key
                source.replace(destination)
                staged.files.append((source, destination))
            return staged
        except Exception:
            staged.restore()
            raise

    def recover_staged_deletions(self, is_referenced: Callable[[str], bool]) -> tuple[int, int]:
        """Recover interrupted deletion while the application is offline.

        A live metadata row means its transaction rolled back and bytes must be
        restored. Otherwise the account/file row committed and bytes are purged.
        """
        if not self.root.exists():
            return 0, 0
        restored = purged = 0
        for directory in self.root.glob(".account-deletion-*"):
            if (not re.fullmatch(r"\.account-deletion-[0-9a-f]{32}", directory.name)
                    or directory.is_symlink() or not directory.is_dir()):
                raise StorageError("Invalid staged-deletion directory.")
            for staged in directory.iterdir():
                if staged.is_symlink() or not staged.is_file():
                    raise StorageError("Invalid staged private upload.")
                original = self._path(staged.name)
                if is_referenced(staged.name):
                    if original.exists():
                        raise StorageError("A referenced private upload already exists.")
                    staged.replace(original)
                    restored += 1
                else:
                    staged.unlink()
                    purged += 1
            directory.rmdir()
        return restored, purged


class StagedDeletion:
    """Private files pending a matching account-deletion transaction."""

    def __init__(self, directory: Path | None, files: list[tuple[Path, Path]]):
        self.directory = directory
        self.files = files

    def restore(self) -> None:
        for source, staged in reversed(self.files):
            if staged.exists():
                if source.exists():
                    raise StorageError("Cannot restore a private upload over another file.")
                staged.replace(source)
        if self.directory is not None:
            self.directory.rmdir()

    def purge(self) -> None:
        for _, staged in self.files:
            staged.unlink(missing_ok=True)
        if self.directory is not None:
            self.directory.rmdir()


def get_storage() -> StorageBackend:
    """Select the backend without binding routes to filesystem operations."""
    if current_app.config["ENV_NAME"] == "production":
        raise StorageError("Configure durable private storage before production uploads.")
    if current_app.config["STORAGE_BACKEND"] != "local":
        raise StorageError("Storage backend is unavailable.")
    return LocalStorage(current_app.config["UPLOAD_STORAGE_ROOT"], current_app.static_folder)


def get_account_deletion_storage() -> LocalStorage:
    """Access existing local private files for erasure in every environment.

    Production's upload guard remains in get_storage; deleting older local
    uploads must still be possible when the configured backend is local.
    """
    if current_app.config["STORAGE_BACKEND"] != "local":
        raise StorageError("Account deletion requires private local storage.")
    return LocalStorage(current_app.config["UPLOAD_STORAGE_ROOT"], current_app.static_folder)
