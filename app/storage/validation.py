"""Validate untrusted upload names, sizes, declared types, and file signatures."""

from __future__ import annotations

import hashlib
import io
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from pypdf import PdfReader
import olefile
from olefile.olefile import OleFileError


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


def count_word_document_pages(data: bytes, extension: str) -> int | None:
    """Read a Word document's last saved pagination count when available.

    Word pagination depends on fonts, layout settings, and the renderer. DOCX
    and legacy DOC store a cached count when a paginating editor last saved
    them; unknown counts remain unset rather than being guessed from text.
    """
    try:
        if extension == "doc":
            document = olefile.OleFileIO(io.BytesIO(data))
            try:
                count = document.get_metadata().num_pages
            finally:
                document.close()
            return count if type(count) is int and count > 0 else None
        if extension != "docx":
            return None
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            try:
                properties = archive.getinfo("docProps/app.xml")
                if properties.file_size > 256 * 1024:
                    return None
                root = ET.fromstring(archive.read(properties))
                pages = next((node.text for node in root.iter()
                              if node.tag.rsplit("}", 1)[-1] == "Pages"), None)
                pages = (pages or "").strip()
                if pages.isdecimal() and int(pages) > 0:
                    return int(pages)
            except KeyError:
                pass
            document_xml = archive.getinfo("word/document.xml")
            if document_xml.file_size > 4 * 1024 * 1024:
                return None
            root = ET.fromstring(archive.read(document_xml))
            rendered_breaks = sum(node.tag.rsplit("}", 1)[-1] == "lastRenderedPageBreak"
                                  for node in root.iter())
            return rendered_breaks + 1 if rendered_breaks else None
    except (OSError, ValueError, RuntimeError, EOFError, NotImplementedError,
            zipfile.BadZipFile, ET.ParseError, OleFileError):
        return None


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
