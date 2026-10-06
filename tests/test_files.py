"""Private upload, ownership, validation, and print-setting behavior."""

import hashlib
import io
import re
import zipfile
from pathlib import Path

import pytest
from flask import g
from sqlalchemy import event
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.extensions import db
from app.models import ColorMode, PaperSize, PrintConfiguration, UploadedFile, User, UserRole
from app.storage import LocalStorage, StorageError
from app.storage.validation import count_word_document_pages


from test_orders import PDF, pdf_bytes
PASSWORD = "A-strong-password-123"


def token(response):
    match = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', response.data)
    assert match
    return match.group(1).decode()


def make_user(app, email="student@example.com", role=UserRole.STUDENT):
    with app.app_context():
        user = User(name="Test Student", email=email, role=role)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
        return user.id


def sign_in(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
    g.pop("_login_user", None)


def post_upload(client, content=PDF, name="notes.pdf", mime="application/pdf", csrf=True):
    data = {"file": (io.BytesIO(content), name, mime)}
    if csrf:
        data["csrf_token"] = token(client.get("/files/upload"))
    return client.post("/files/upload", data=data, content_type="multipart/form-data")


def configure(client, file_id, **changes):
    data = {
        "csrf_token": token(client.get(f"/files/{file_id}/configure")),
        "paper_size": "A4",
        "color_mode": "GRAYSCALE",
        "quantity": "2",
    }
    data.update(changes)
    return client.post(f"/files/{file_id}/configure", data=data)


def uploaded_id(app):
    with app.app_context():
        return db.session.scalar(select(UploadedFile)).id


def test_upload_metadata_listing_detail_and_download(client, test_app):
    user_id = make_user(test_app)
    sign_in(client, user_id)
    response = post_upload(client, name="my notes.pdf")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/files/1")
    detail = client.get(response.headers["Location"])
    assert b"File uploaded successfully" in detail.data
    assert b"No order has been submitted" in detail.data
    assert b"my_notes.pdf" in detail.data
    assert b"my_notes.pdf" in client.get("/files").data
    download = client.get("/files/1/download")
    assert download.data == PDF
    assert b"attachment" in download.headers["Content-Disposition"].encode()
    assert download.headers["Cache-Control"] == "private, no-store"
    assert download.headers["X-Content-Type-Options"] == "nosniff"

    with test_app.app_context():
        record = db.session.get(UploadedFile, 1)
        assert record.user_id == user_id
        assert record.file_size == len(PDF)
        assert record.file_extension == "pdf"
        assert record.mime_type == "application/pdf"
        assert record.sha256 == hashlib.sha256(PDF).hexdigest()
        assert record.pdf_page_count == 1
        assert re.fullmatch(r"[0-9a-f]{32}\.pdf", record.storage_key)
        assert record.stored_filename == record.storage_key
        assert record.created_at and record.updated_at
        assert Path(test_app.config["UPLOAD_STORAGE_ROOT"], record.storage_key).read_bytes() == PDF
        assert record.configuration is None
        assert client.get(f"/static/{record.storage_key}").status_code == 404


@pytest.mark.parametrize("name,content,mime", [
    ("scan.JPG", b"\xff\xd8\xffphoto\xff\xd9", "image/jpeg"),
    ("scan.jpeg", b"\xff\xd8\xffphoto\xff\xd9", "image/jpeg"),
    ("image.png", b"\x89PNG\r\n\x1a\nimage", "image/png"),
    ("essay.doc", bytes.fromhex("d0cf11e0a1b11ae1") + b"legacy", "application/msword"),
    ("slides.ppt", bytes.fromhex("d0cf11e0a1b11ae1") + b"legacy", "application/vnd.ms-powerpoint"),
])
def test_other_allowed_signatures(client, test_app, name, content, mime):
    sign_in(client, make_user(test_app))
    assert post_upload(client, content, name, mime).status_code == 302
    with test_app.app_context():
        assert db.session.scalar(select(UploadedFile)).file_extension == name.rsplit(".", 1)[1].lower()


@pytest.mark.parametrize("name,content,mime,message", [
    ("evil.exe", b"MZ executable", "application/octet-stream", b"Unsupported file type"),
    ("fake.pdf", b"MZ executable", "application/pdf", b"content does not match"),
    ("fake.pdf", PDF, "text/plain", b"type does not match"),
    ("../notes.pdf", PDF, "application/pdf", b"without folder paths"),
])
def test_bad_uploads_are_rejected(client, test_app, name, content, mime, message):
    sign_in(client, make_user(test_app))
    response = post_upload(client, content, name, mime)
    assert response.status_code == 400
    assert message in response.data
    with test_app.app_context():
        assert db.session.scalar(select(UploadedFile)) is None
    assert not list(Path(test_app.config["UPLOAD_STORAGE_ROOT"]).glob("*"))


def test_missing_and_oversize_uploads(client, test_app):
    sign_in(client, make_user(test_app))
    missing = client.post("/files/upload", data={"csrf_token": token(client.get("/files/upload"))})
    assert missing.status_code == 400
    assert b"Select a file" in missing.data
    test_app.config["UPLOAD_MAX_SIZE"] = len(PDF) - 1
    too_large = post_upload(client)
    assert too_large.status_code == 413
    assert b"File is too large" in too_large.data
    test_app.config["MAX_CONTENT_LENGTH"] = 32
    request_cap = post_upload(client, content=PDF * 20)
    assert request_cap.status_code == 413
    with test_app.app_context():
        assert db.session.scalar(select(UploadedFile)) is None


def test_ownership_role_boundary_and_missing_ids(client, test_app):
    owner = make_user(test_app)
    other = make_user(test_app, "other@example.com")
    staff = make_user(test_app, "staff@example.com", UserRole.SHOP_STAFF)
    sign_in(client, owner)
    assert post_upload(client).status_code == 302
    file_id = uploaded_id(test_app)
    sign_in(client, other)
    assert b"notes.pdf" not in client.get("/files").data
    for path in (f"/files/{file_id}", f"/files/{file_id}/download", f"/files/{file_id}/configure"):
        assert client.get(path).status_code == 404
    assert client.post(
        f"/files/{file_id}/configure",
        data={"csrf_token": token(client.get("/files")), "paper_size": "A4", "color_mode": "COLOR", "quantity": "1"},
    ).status_code == 404
    assert client.post(f"/files/{file_id}/delete", data={"csrf_token": token(client.get("/files"))}).status_code == 404
    assert client.get("/files/9999").status_code == 404
    sign_in(client, staff)
    for path in ("/files", "/files/upload", f"/files/{file_id}", f"/files/{file_id}/download", f"/files/{file_id}/configure"):
        assert client.get(path).status_code == 403
    assert client.post(f"/files/{file_id}/delete", data={"csrf_token": token(client.get("/shop"))}).status_code == 403
    with client.session_transaction() as session:
        session.clear()
    g.pop("_login_user", None)
    assert client.get("/files").status_code == 302


def test_oversized_file_id_does_not_reach_database(client, test_app):
    sign_in(client, make_user(test_app))
    oversized = 2**63
    csrf_token = token(client.get("/files"))
    for path in (
        f"/files/{oversized}",
        f"/files/{oversized}/download",
        f"/files/{oversized}/configure",
    ):
        assert client.get(path).status_code == 404
    assert client.post(
        f"/files/{oversized}/configure", data={"csrf_token": csrf_token}
    ).status_code == 404
    assert client.post(
        f"/files/{oversized}/delete", data={"csrf_token": csrf_token}
    ).status_code == 404


@pytest.mark.parametrize("paper_size", [member.value for member in PaperSize])
@pytest.mark.parametrize("color_mode", [member.value for member in ColorMode])
def test_configuration_accepts_shared_choices(client, test_app, paper_size, color_mode):
    sign_in(client, make_user(test_app))
    assert post_upload(client).status_code == 302
    response = configure(client, 1, paper_size=paper_size, color_mode=color_mode, quantity="1", is_rush="y")
    assert response.status_code == 302
    with test_app.app_context():
        config = db.session.scalar(select(PrintConfiguration))
        assert config.file_id == 1
        assert config.paper_size == PaperSize(paper_size)
        assert config.color_mode == ColorMode(color_mode)
        assert config.quantity == 1
        assert config.is_rush is True
        assert config.created_at and config.updated_at
    assert b"Print configuration" in client.get("/files/1").data


def test_configuration_updates_one_active_record_and_persists(client, test_app):
    sign_in(client, make_user(test_app))
    post_upload(client)
    assert configure(client, 1, paper_size="LETTER", quantity="3", is_rush="y").status_code == 302
    assert configure(client, 1, paper_size="A2", color_mode="COLOR", quantity="4").status_code == 302
    with test_app.app_context():
        configs = db.session.scalars(select(PrintConfiguration)).all()
        assert len(configs) == 1
        assert configs[0].paper_size == PaperSize.A2
        assert configs[0].color_mode == ColorMode.COLOR
        assert configs[0].quantity == 4
        assert configs[0].is_rush is False
        assert db.session.get(UploadedFile, 1).configuration.id == configs[0].id
    page = client.get("/files/1/configure")
    assert b"value=\"4\"" in page.data


@pytest.mark.parametrize("changes,message", [
    ({"paper_size": "TABLOID"}, b"Not a valid choice"),
    ({"color_mode": "NEON"}, b"Not a valid choice"),
    ({"quantity": "0"}, b"at least 1"),
    ({"quantity": "-1"}, b"at least 1"),
    ({"quantity": "1000"}, b"cannot exceed"),
    ({"quantity": "many"}, b"integer"),
])
def test_invalid_configuration_is_not_saved(client, test_app, changes, message):
    sign_in(client, make_user(test_app))
    post_upload(client)
    response = configure(client, 1, **changes)
    assert response.status_code == 200
    assert message in response.data
    with test_app.app_context():
        assert db.session.scalar(select(PrintConfiguration)) is None


def test_configurable_quantity_max(client, test_app):
    sign_in(client, make_user(test_app))
    post_upload(client)
    test_app.config["UPLOAD_MAX_QUANTITY"] = 5
    assert configure(client, 1, quantity="6").status_code == 200
    assert configure(client, 1, quantity="5").status_code == 302


def test_missing_stored_file_and_corrupt_key_fail_safely(client, test_app):
    sign_in(client, make_user(test_app))
    post_upload(client)
    with test_app.app_context():
        record = db.session.get(UploadedFile, 1)
        original_key = record.storage_key
    Path(test_app.config["UPLOAD_STORAGE_ROOT"], original_key).unlink()
    response = client.get("/files/1/download")
    assert response.status_code == 404
    assert test_app.config["UPLOAD_STORAGE_ROOT"].encode() not in response.data
    with test_app.app_context():
        record = db.session.get(UploadedFile, 1)
        record.storage_key = "../outside.pdf"
        db.session.commit()
    assert client.get("/files/1/download").status_code == 404
    deleted = client.post("/files/1/delete", data={"csrf_token": token(client.get("/files/1"))})
    assert deleted.status_code == 503
    assert b"removed from your account" in deleted.data
    assert test_app.config["UPLOAD_STORAGE_ROOT"].encode() not in deleted.data
    with test_app.app_context():
        assert db.session.get(UploadedFile, 1) is None


def test_changed_stored_bytes_are_not_downloaded(client, test_app):
    sign_in(client, make_user(test_app))
    post_upload(client)
    with test_app.app_context():
        key = db.session.get(UploadedFile, 1).storage_key
    Path(test_app.config["UPLOAD_STORAGE_ROOT"], key).write_bytes(b"tampered")
    assert client.get("/files/1/download").status_code == 404


def test_storage_read_error_does_not_expose_private_path(client, test_app, monkeypatch):
    sign_in(client, make_user(test_app))
    assert post_upload(client).status_code == 302

    def fail_read(self, key):
        raise OSError("C:\\private\\secret")

    monkeypatch.setattr(LocalStorage, "read", fail_read)
    response = client.get("/files/1/download")
    assert response.status_code == 503
    assert b"C:\\private\\secret" not in response.data


def test_storage_rejects_traversal_and_public_static_root(test_app, tmp_path):
    storage = LocalStorage(tmp_path / "uploads", test_app.static_folder)
    with pytest.raises(StorageError):
        storage.read("../secret.pdf")
    with pytest.raises(StorageError):
        storage.delete("f" * 32 + ".exe")
    with pytest.raises(StorageError):
        LocalStorage(test_app.static_folder, test_app.static_folder)


def test_production_has_no_implicit_local_upload_backend(client, test_app):
    sign_in(client, make_user(test_app))
    test_app.config["ENV_NAME"] = "production"
    assert post_upload(client).status_code == 503
    with test_app.app_context():
        assert db.session.scalar(select(UploadedFile)) is None


@pytest.mark.parametrize("path,kind", [
    ("/files/upload", "upload"),
    ("/files/1/configure", "configure"),
    ("/files/1/delete", "delete"),
])
def test_mutations_require_csrf(client, test_app, path, kind):
    sign_in(client, make_user(test_app))
    if kind != "upload":
        post_upload(client)
    response = client.post(path, data={})
    assert response.status_code == 400


def test_delete_removes_file_and_configuration(client, test_app):
    sign_in(client, make_user(test_app))
    post_upload(client)
    configure(client, 1)
    with test_app.app_context():
        key = db.session.get(UploadedFile, 1).storage_key
    response = client.post("/files/1/delete", data={"csrf_token": token(client.get("/files/1"))})
    assert response.status_code == 302
    assert not Path(test_app.config["UPLOAD_STORAGE_ROOT"], key).exists()
    with test_app.app_context():
        assert db.session.get(UploadedFile, 1) is None
        assert db.session.scalar(select(PrintConfiguration)) is None
    assert client.get("/files/1").status_code == 404


def test_failed_database_delete_keeps_private_bytes(client, test_app):
    sign_in(client, make_user(test_app))
    assert post_upload(client).status_code == 302
    with test_app.app_context():
        key = db.session.get(UploadedFile, 1).storage_key

    def fail_commit(session):
        raise SQLAlchemyError("simulated database failure")

    event.listen(Session, "before_commit", fail_commit)
    try:
        response = client.post(
            "/files/1/delete", data={"csrf_token": token(client.get("/files/1"))}
        )
    finally:
        event.remove(Session, "before_commit", fail_commit)

    assert response.status_code == 500
    assert Path(test_app.config["UPLOAD_STORAGE_ROOT"], key).read_bytes() == PDF
    with test_app.app_context():
        assert db.session.get(UploadedFile, 1) is not None


def test_upload_commit_and_cleanup_failures_still_return_safe_error(
    client, test_app, monkeypatch
):
    sign_in(client, make_user(test_app))

    def fail_commit(session):
        raise SQLAlchemyError("simulated database failure")

    def fail_delete(self, key):
        raise OSError("C:\\private\\secret")

    monkeypatch.setattr(LocalStorage, "delete", fail_delete)
    event.listen(Session, "before_commit", fail_commit)
    try:
        response = post_upload(client)
    finally:
        event.remove(Session, "before_commit", fail_commit)

    assert response.status_code == 500
    assert b"C:\\private\\secret" not in response.data
    with test_app.app_context():
        assert db.session.scalar(select(UploadedFile)) is None


def test_missing_bytes_can_be_removed_and_cleanup_failure_is_reported(
    client, test_app, monkeypatch
):
    sign_in(client, make_user(test_app))
    assert post_upload(client).status_code == 302
    with test_app.app_context():
        key = db.session.get(UploadedFile, 1).storage_key
    path = Path(test_app.config["UPLOAD_STORAGE_ROOT"], key)
    path.unlink()
    assert client.post(
        "/files/1/delete", data={"csrf_token": token(client.get("/files/1"))}
    ).status_code == 302
    with test_app.app_context():
        assert db.session.get(UploadedFile, 1) is None

    second = post_upload(client)
    assert second.status_code == 302
    second_url = second.headers["Location"]

    def fail_delete(self, key):
        raise OSError("C:\\private\\secret")

    monkeypatch.setattr(LocalStorage, "delete", fail_delete)
    failed = client.post(
        second_url + "/delete", data={"csrf_token": token(client.get(second_url))}
    )
    assert failed.status_code == 503
    assert b"removed from your account" in failed.data
    assert b"C:\\private\\secret" not in failed.data
    with test_app.app_context():
        assert db.session.scalar(select(UploadedFile)) is None


@pytest.mark.parametrize("extension,path", [("docx", "word/document.xml"), ("pptx", "ppt/presentation.xml")])
def test_ooxml_content_checked(client, test_app, extension, path):
    sign_in(client, make_user(test_app))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        main_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
            if extension == "docx" else
            "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
        )
        archive.writestr("[Content_Types].xml", f'<Types><Override ContentType="{main_type}"/></Types>')
        archive.writestr(path, "<root/>")
    assert post_upload(client, buffer.getvalue(), f"slides.{extension}", "application/octet-stream").status_code == 302
    assert post_upload(client, b"PK fake zip", f"bad.{extension}", "application/octet-stream").status_code == 400


def test_docx_upload_does_not_trust_saved_word_pages_without_renderer(monkeypatch, client, test_app):
    monkeypatch.setattr("app.storage.validation.shutil.which", lambda name: None)
    sign_in(client, make_user(test_app))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types><Override ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr("docProps/app.xml", "<Properties><Pages>4</Pages></Properties>")
    response = post_upload(client, buffer.getvalue(), "handout.docx",
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert response.status_code == 302
    with test_app.app_context():
        record = db.session.scalar(select(UploadedFile))
        assert record.pdf_page_count is None


def test_docx_does_not_trust_saved_rendered_page_breaks_without_renderer(monkeypatch):
    monkeypatch.setattr("app.storage.validation.shutil.which", lambda name: None)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types><Override ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:lastRenderedPageBreak/><w:lastRenderedPageBreak/></w:document>',
        )
    assert count_word_document_pages(buffer.getvalue(), "docx") is None


def test_docx_renderer_overrides_stale_one_page_metadata(monkeypatch, client, test_app):
    sign_in(client, make_user(test_app))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", '<Types><Override ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr("docProps/app.xml", "<Properties><Pages>1</Pages></Properties>")

    monkeypatch.setattr("app.storage.validation.shutil.which",
                        lambda name: "/usr/bin/soffice" if name == "soffice" else None)

    def convert(command, *, cwd, capture_output, timeout, check):
        assert command[0] == "/usr/bin/soffice"
        assert command[command.index("--convert-to") + 1] == "pdf:writer_pdf_Export"
        (cwd / "document.pdf").write_bytes(pdf_bytes(2))

    monkeypatch.setattr("app.storage.validation.subprocess.run", convert)
    response = post_upload(client, buffer.getvalue(), "two-pages.docx",
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert response.status_code == 302
    with test_app.app_context():
        assert db.session.scalar(select(UploadedFile)).pdf_page_count == 2


def test_docx_does_not_treat_stale_one_page_metadata_as_verified(monkeypatch):
    monkeypatch.setattr("app.storage.validation.shutil.which", lambda name: None)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr("docProps/app.xml", "<Properties><Pages>1</Pages></Properties>")
    assert count_word_document_pages(buffer.getvalue(), "docx") is None


def test_doc_uses_abiword_rendered_pdf_when_available(monkeypatch):
    monkeypatch.setattr("app.storage.validation.shutil.which",
                        lambda name: "/usr/bin/abiword" if name == "abiword" else None)

    def convert(command, *, cwd, capture_output, timeout, check):
        assert command[:2] == ["/usr/bin/abiword", "--to=pdf"]
        (cwd / "document.pdf").write_bytes(pdf_bytes(6))

    monkeypatch.setattr("app.storage.validation.subprocess.run", convert)
    assert count_word_document_pages(bytes.fromhex("d0cf11e0a1b11ae1"), "doc") == 6


def test_word_renderer_finds_default_windows_libreoffice_path(monkeypatch, tmp_path):
    executable = tmp_path / "LibreOffice" / "program" / "soffice.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"test executable")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("WORD_CONVERTER_PATH", raising=False)
    monkeypatch.setattr("app.storage.validation.shutil.which", lambda name: None)

    def convert(command, *, cwd, capture_output, timeout, check):
        assert command[0] == str(executable)
        (cwd / "document.pdf").write_bytes(pdf_bytes(2))

    monkeypatch.setattr("app.storage.validation.subprocess.run", convert)
    assert count_word_document_pages(b"docx content", "docx") == 2


def test_page_count_cli_reports_pdf_pages(test_app, tmp_path):
    document = tmp_path / "two.pdf"
    document.write_bytes(pdf_bytes(2))
    result = test_app.test_cli_runner().invoke(args=["check-page-count", str(document)])
    assert result.exit_code == 0
    assert "Document pages: 2" in result.output


def test_ooxml_wrong_main_type_and_macro_entry_rejected(client, test_app):
    sign_in(client, make_user(test_app))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<root/>")
    assert post_upload(client, buffer.getvalue(), "bad.docx", "application/octet-stream").status_code == 400
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
        )
        archive.writestr("word/document.xml", "<root/>")
        archive.writestr("word/vbaProject.bin", "macro")
    assert post_upload(client, buffer.getvalue(), "macro.docx", "application/octet-stream").status_code == 400
