"""Validate untrusted upload names, sizes, declared types, and file signatures."""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


# This is the sole allowlist for uploads. Configuration may restrict size, not add types.
MIME_TYPES = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
}
ALLOWED_EXTENSIONS = frozenset(MIME_TYPES)
OLE_SIGNATURE = bytes.fromhex("d0cf11e0a1b11ae1")
OOXML_MAIN_TYPES = {
    "docx": b"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    "pptx": b"application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
}


class UploadValidationError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ValidatedUpload:
    original_filename: str
    extension: str
    mime_type: str
    data: bytes
    sha256: str

    @property
    def size(self) -> int:
        return len(self.data)


def _matches_signature(data: bytes, extension: str) -> bool:
    if extension == "pdf":
        return data.startswith(b"%PDF-")
    if extension == "png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if extension in {"jpg", "jpeg"}:
        return data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9")
    if extension in {"doc", "ppt"}:
        return data.startswith(OLE_SIGNATURE)
    if extension in {"docx", "pptx"}:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = set(archive.namelist())
                expected = "word/document.xml" if extension == "docx" else "ppt/presentation.xml"
                if "[Content_Types].xml" not in names or expected not in names:
                    return False
                if any(name.endswith("vbaProject.bin") for name in names):
                    return False
                content_types = archive.getinfo("[Content_Types].xml")
                if content_types.file_size > 1024 * 1024:
                    return False
                return OOXML_MAIN_TYPES[extension] in archive.read("[Content_Types].xml")
        except (OSError, ValueError, RuntimeError, EOFError, NotImplementedError, zipfile.BadZipFile):
            return False
    return False


def validate_upload(upload: FileStorage | None, max_size: int) -> ValidatedUpload:
    if upload is None or not upload.filename:
        raise UploadValidationError("Select a file to upload.")
    if "/" in upload.filename or "\\" in upload.filename:
        raise UploadValidationError("Use a file name without folder paths.")
    filename = secure_filename(upload.filename)
    if not filename or "." not in filename or len(filename) > 255:
        raise UploadValidationError("Choose a file with a valid name and extension.")
    extension = filename.rsplit(".", 1)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise UploadValidationError("Unsupported file type.")
    declared = (upload.mimetype or "").lower()
    if declared not in {"", "application/octet-stream", MIME_TYPES[extension]}:
        raise UploadValidationError("File type does not match its extension.")
    data = upload.stream.read(max_size + 1)
    if len(data) > max_size:
        raise UploadValidationError("File is too large.", 413)
    if not data or not _matches_signature(data, extension):
        raise UploadValidationError("File content does not match its extension.")
    return ValidatedUpload(
        original_filename=filename,
        extension=extension,
        mime_type=MIME_TYPES[extension],
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
    )
