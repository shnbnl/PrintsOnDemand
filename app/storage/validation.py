"""Validate untrusted upload names, sizes, declared types, and file signatures."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from pypdf import PdfReader


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
    pdf_page_count: int | None = None

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


def count_pdf_pages(data: bytes) -> int:
    """Read the actual page tree, rejecting encrypted, malformed, or empty PDFs."""
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise UploadValidationError("Unable to read this PDF. Please upload an unencrypted, valid PDF.")
        pages = len(reader.pages)
        if pages < 1:
            raise UploadValidationError("Unable to read this PDF. Please upload a valid PDF.")
        return pages
    except UploadValidationError:
        raise
    except Exception as error:
        raise UploadValidationError("Unable to read this PDF. Please upload a valid PDF.") from error


def word_converters() -> list[tuple[str, str]]:
    """Find a headless renderer, including LibreOffice's default Windows path."""
    candidates = []
    configured = os.environ.get("WORD_CONVERTER_PATH", "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            candidates.append(str(candidate))
    for name in ("soffice", "libreoffice", "abiword"):
        executable = shutil.which(name)
        if executable:
            candidates.append(executable)
    for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if root:
            candidate = Path(root) / "LibreOffice" / "program" / "soffice.exe"
            if candidate.is_file():
                candidates.append(str(candidate))

    converters = []
    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        name = "abiword" if "abiword" in Path(candidate).name.lower() else "soffice"
        converters.append((name, candidate))
        seen.add(candidate)
    return converters


def _render_word_document_pages(data: bytes, extension: str) -> int | None:
    """Count the pages a local office renderer would print, when available."""
    if extension not in {"doc", "docx"}:
        return None
    converters = word_converters()
    if not converters:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="pod-pages-") as directory:
            root = Path(directory)
            source = root / f"document.{extension}"
            target = root / "document.pdf"
            source.write_bytes(data)
            for name, executable in converters:
                target.unlink(missing_ok=True)
                if name == "abiword":
                    command = [executable, "--to=pdf", str(source)]
                else:
                    profile = (root / f"profile-{name}").as_uri()
                    command = [executable, f"-env:UserInstallation={profile}", "--headless",
                               "--nodefault", "--norestore", "--convert-to", "pdf:writer_pdf_Export",
                               "--outdir", str(root), str(source)]
                try:
                    subprocess.run(command, cwd=root, capture_output=True, timeout=30, check=False)
                    if target.is_file() and target.stat().st_size <= 64 * 1024 * 1024:
                        return count_pdf_pages(target.read_bytes())
                except (OSError, subprocess.TimeoutExpired, UploadValidationError):
                    continue
    except OSError:
        return None
    return None


def count_word_document_pages(data: bytes, extension: str) -> int | None:
    """Use rendered output, never Word's potentially stale saved page count."""
    return _render_word_document_pages(data, extension)


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
    page_count = (count_pdf_pages(data) if extension == "pdf" else
                  count_word_document_pages(data, extension) if extension in {"doc", "docx"} else None)
    return ValidatedUpload(
        original_filename=filename,
        extension=extension,
        mime_type=MIME_TYPES[extension],
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        pdf_page_count=page_count,
    )
