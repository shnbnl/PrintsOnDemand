"""Guided checkout: order, payment, file ownership, and fulfillment boundaries."""

from decimal import Decimal
import hashlib
from io import BytesIO
import zipfile

import pytest

from sqlalchemy import select

from app.extensions import db
from app.models import ColorMode, Order, PaperSize, PaymentMethod, PaymentStatus, PrintConfiguration, PrintPrice, PrintingShop, UploadedFile, UserRole
from app.services.fulfillment import FulfillmentError
from app.services.pricing import PricingError, quote_cart
from app.storage import LocalStorage
from test_orders import (
    PDF, pdf_bytes, approved_professor, file, offer_professor_service, pickup_fields,
    shop, sign_in, student, token,
)


def post(client, path, data=None):
    return client.post(path, data={"csrf_token": token(client.get("/checkout/upload")), **(data or {})})


def setup(client, app, *, professor=False, online=False):
    owner = student(app, role=UserRole.PROFESSOR if professor else UserRole.STUDENT)
    shop_id = shop(app)
    if online:
        with app.app_context():
            record = db.session.get(PrintingShop, shop_id)
            record.online_enabled = True
            record.online_instructions = "Use the configured shop account."
            record.online_account_name = "Campus Prints"
            record.online_account_reference = "Sample account 12345"
            db.session.commit()
    sign_in(client, owner)
    file_id = upload_checkout_file(client, app, owner)
    return owner, shop_id, file_id


def upload_checkout_file(client, app, owner, name="notes.pdf"):
    response = client.post("/checkout/upload/files", data={
        "csrf_token": token(client.get("/checkout/upload")),
        "files": (BytesIO(PDF), name),
    }, content_type="multipart/form-data")
    assert response.status_code == 302
    with app.app_context():
        return db.session.scalar(select(UploadedFile.id).where(
            UploadedFile.user_id == owner, UploadedFile.original_filename == name,
        ).order_by(UploadedFile.id.desc()))


@pytest.mark.parametrize(("professor", "desk_path"), [(False, "/student"), (True, "/professor")])
def test_upload_page_returns_to_role_workspace_without_losing_staged_files(
    client, test_app, professor, desk_path,
):
    _, _, file_id = setup(client, test_app, professor=professor)
    upload_page = client.get("/checkout/upload")
    assert upload_page.status_code == 200
    assert f'href="{desk_path}"'.encode() in upload_page.data
    assert b'aria-label="Back to Printing Desk"' in upload_page.data
    assert b'class="vector-back checkout-back-to-desk"' in upload_page.data
    assert b'<svg ' in upload_page.data

    desk = client.get(desk_path)
    assert desk.status_code == 200
    upload_again = client.get("/checkout/upload")
    assert upload_again.status_code == 200
    assert b"notes.pdf" in upload_again.data
    with test_app.app_context():
        assert db.session.get(UploadedFile, file_id) is not None


def test_upload_progress_requests_keep_validation_and_store_files(client, test_app):
    owner = student(test_app)
    sign_in(client, owner)
    upload_page = client.get("/checkout/upload")
    assert b"data-checkout-upload" in upload_page.data
    assert b"checkout-upload.js" in upload_page.data
    csrf_token = token(upload_page)

    rejected = client.post("/checkout/upload/files", data={
        "csrf_token": csrf_token,
        "files": (BytesIO(b"not a PDF"), "invalid.pdf"),
    }, content_type="multipart/form-data", headers={"Accept": "application/json"})
    assert rejected.status_code == 400
    assert rejected.json == {"error": "File content does not match its extension."}

    accepted = client.post("/checkout/upload/files", data={
        "csrf_token": csrf_token,
        "files": (BytesIO(pdf_bytes(2)), "two-pages.pdf"),
    }, content_type="multipart/form-data", headers={"Accept": "application/json"})
    assert accepted.status_code == 200
    assert accepted.json == {"redirect": "/checkout/upload"}
    with test_app.app_context():
        record = db.session.scalar(select(UploadedFile).where(UploadedFile.user_id == owner))
        assert record.original_filename == "two-pages.pdf"
        assert record.pdf_page_count == 2

    test_app.config["MAX_CONTENT_LENGTH"] = 32
    too_large = client.post("/checkout/upload/files", data={
        "csrf_token": csrf_token,
        "files": (BytesIO(PDF), "too-large.pdf"),
    }, content_type="multipart/form-data", headers={"Accept": "application/json"})
    assert too_large.status_code == 413
    assert "combined upload is too large" in too_large.json["error"]


@pytest.mark.parametrize(("name", "content", "mime"), [
    ("sample.pdf", PDF, "application/pdf"),
    ("sample.jpg", b"\xff\xd8\xffphoto\xff\xd9", "image/jpeg"),
    ("sample.png", b"\x89PNG\r\n\x1a\nimage", "image/png"),
])
def test_progress_upload_accepts_pdf_jpeg_and_png(client, test_app, name, content, mime):
    owner = student(test_app)
    sign_in(client, owner)
    response = client.post("/checkout/upload/files", data={
        "csrf_token": token(client.get("/checkout/upload")),
        "files": (BytesIO(content), name, mime),
    }, content_type="multipart/form-data", headers={"Accept": "application/json"})
    assert response.status_code == 200
    with test_app.app_context():
        assert db.session.scalar(select(UploadedFile).where(UploadedFile.user_id == owner)).original_filename == name


def test_progress_upload_accepts_docx_even_without_page_renderer(monkeypatch, client, test_app):
    monkeypatch.setattr("app.storage.validation.shutil.which", lambda name: None)
    owner = student(test_app)
    sign_in(client, owner)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", '<Types><Override ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr("word/document.xml", "<document/>")
    response = client.post("/checkout/upload/files", data={
        "csrf_token": token(client.get("/checkout/upload")),
        "files": (BytesIO(buffer.getvalue()), "sample.docx",
                  "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    }, content_type="multipart/form-data", headers={"Accept": "application/json"})
    assert response.status_code == 200
    with test_app.app_context():
        record = db.session.scalar(select(UploadedFile).where(UploadedFile.user_id == owner))
        assert record.original_filename == "sample.docx"
        assert record.pdf_page_count is None


def print_fields(file_id, *, quantity="1"):
    return {"file_id": str(file_id), f"paper_size_{file_id}": "A4",
            f"color_mode_{file_id}": "GRAYSCALE", f"quantity_{file_id}": quantity}


def start(client, shop_id, file_id, *, quantity="2", destination=None):
    uploaded = post(client, "/checkout/upload", {"file_id": str(file_id)})
    assert uploaded.status_code == 302, uploaded.get_data(as_text=True)[:500]
    selected = post(client, "/checkout/shop", {"shop_id": str(shop_id), **print_fields(file_id, quantity=quantity)})
    assert selected.status_code == 302, selected.get_data(as_text=True)[:500]
    return post(client, "/checkout/fulfillment", destination or pickup_fields())


def test_student_cash_checkout_creates_order_payment_and_success(client, test_app):
    owner, shop_id, file_id = setup(client, test_app)
    assert start(client, shop_id, file_id).headers["Location"].endswith("/checkout/payment")
    assert b"PHP 4.50" in client.get("/checkout/payment").data
    assert post(client, "/checkout/payment", {"payment_method": "ONSITE"}).status_code == 302
    assert b"Pay Onsite" in client.get("/checkout/review").data
    placed = post(client, "/checkout/place", {"total": "0.01", "shop_id": "9999"})
    assert placed.status_code == 302 and "/checkout/success/" in placed.headers["Location"]
    confirmation = client.get(placed.headers["Location"])
    assert b"Order Created Successfully!" in confirmation.data
    assert b'class="order-print-transition"' in confirmation.data
    assert b"PHP 4.50" in confirmation.data
    assert b'class="order-print-transition"' not in client.get(placed.headers["Location"]).data
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert order.user_id == owner and order.shop_id == shop_id
        assert order.order_reference.encode() in confirmation.data
        assert order.total == Decimal("4.50")
        assert [item.uploaded_file_id for item in order.items] == [file_id]
        assert order.payment.payment_method == PaymentMethod.ONSITE
        assert order.payment.payment_status == PaymentStatus.PENDING
    order_detail = client.get(f"/orders/{order.order_reference}")
    assert b"Choose or review your method" not in order_detail.data
    assert b'name="payment_method"' not in order_detail.data
    assert client.get("/orders").status_code == 200
    assert client.post("/checkout/place", data={"csrf_token": token(confirmation)}).headers["Location"] == placed.headers["Location"]
    with test_app.app_context():
        assert len(db.session.scalars(select(Order)).all()) == 1


def test_shop_hover_preview_returns_full_shop_panel_without_changing_selection(client, test_app):
    owner = student(test_app)
    selected_id = shop(test_app, name="Selected Shop")
    preview_id = shop(test_app, name="Preview Shop", price="9.50")
    sign_in(client, owner)
    file_id = upload_checkout_file(client, test_app, owner)
    assert post(client, "/checkout/upload", {"file_id": str(file_id)}).status_code == 302
    assert post(client, "/checkout/shop", {
        "shop_id": str(selected_id), **print_fields(file_id),
    }).status_code == 302

    response = client.post("/checkout/shop", data={
        "csrf_token": token(client.get("/checkout/shop")), "intent": "preview",
        "shop_id": str(preview_id), **print_fields(file_id),
    }, headers={"Accept": "application/json"})
    assert response.status_code == 200
    assert response.json["shop_id"] == preview_id
    assert "Preview Shop" in response.json["html"]
    assert "PHP 9.50" in response.json["html"]
    current = client.get("/checkout/shop")
    assert f'data-current-shop="{selected_id}"'.encode() in current.data


def test_student_online_reference_waits_for_verification(client, test_app):
    _, shop_id, file_id = setup(client, test_app, online=True)
    assert start(client, shop_id, file_id).status_code == 302
    payment_page = client.get("/checkout/payment")
    assert b"Payment QR for Campus Prints" in payment_page.data
    assert b"Placeholder QR" not in payment_page.data
    assert post(client, "/checkout/payment", {"payment_method": "ONLINE", "payment_reference": "ABC-1234"}).status_code == 302
    assert post(client, "/checkout/place").status_code == 302
    with test_app.app_context():
        payment = db.session.scalar(select(Order)).payment
        assert payment.payment_method == PaymentMethod.ONLINE
        assert payment.payment_status == PaymentStatus.SUBMITTED
        assert payment.payment_reference == "ABC-1234"


@pytest.mark.parametrize("professor", [False, True])
def test_online_checkout_requires_reference_and_keeps_payment_unverified(client, test_app, professor):
    owner, shop_id, file_id = setup(client, test_app, professor=professor, online=True)
    assert start(client, shop_id, file_id).status_code == 302
    page = client.get("/checkout/payment")
    assert b"Payment Reference Number" in page.data
    assert b"optional before placing" not in page.data
    for reference, message in (
        (None, b"Payment reference number is required for online payment."),
        ("   ", b"Enter your payment reference number."),
        ("A" * 121, b"Payment reference number is too long."),
        ("bad<script>", b"Please enter a valid payment reference number."),
    ):
        payload = {"payment_method": "ONLINE"}
        if reference is not None:
            payload["payment_reference"] = reference
        rejected = post(client, "/checkout/payment", payload)
        assert rejected.status_code == 400
        assert message in rejected.data
        assert b'data-online-payment' in rejected.data
        assert client.get("/checkout/review").headers["Location"].endswith("/checkout/payment")
    accepted = post(client, "/checkout/payment", {
        "payment_method": "ONLINE", "payment_reference": "  ABC  1234  ",
        "amount": "0.01", "payment_status": "PAID", "shop_id": "99999",
    })
    assert accepted.status_code == 302
    assert b"ABC 1234" in client.get("/checkout/review").data
    assert post(client, "/checkout/place", {"amount": "0.01", "payment_status": "PAID"}).status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert order.user_id == owner and order.shop_id == shop_id
        assert order.payment.payment_method == PaymentMethod.ONLINE
        assert order.payment.payment_reference == "ABC 1234"
        assert order.payment.payment_status == PaymentStatus.SUBMITTED
        assert order.payment.amount == order.total


def test_switching_online_to_cash_discards_checkout_reference(client, test_app):
    _, shop_id, file_id = setup(client, test_app, online=True)
    assert start(client, shop_id, file_id).status_code == 302
    assert post(client, "/checkout/payment", {
        "payment_method": "ONLINE", "payment_reference": "ONLINE-1234",
    }).status_code == 302
    assert post(client, "/checkout/payment", {"payment_method": "ONSITE"}).status_code == 302
    assert b"ONLINE-1234" not in client.get("/checkout/review").data
    assert post(client, "/checkout/place").status_code == 302
    with test_app.app_context():
        payment = db.session.scalar(select(Order)).payment
        assert payment.payment_method == PaymentMethod.ONSITE
        assert payment.payment_reference is None
        assert payment.payment_status == PaymentStatus.PENDING


def test_place_rechecks_reference_in_session(client, test_app):
    _, shop_id, file_id = setup(client, test_app, online=True)
    assert start(client, shop_id, file_id).status_code == 302
    assert post(client, "/checkout/payment", {
        "payment_method": "ONLINE", "payment_reference": "VALID-1234",
    }).status_code == 302
    with client.session_transaction() as state:
        saved = state["checkout_draft"].copy()
        saved["payment_reference"] = "   "
        state["checkout_draft"] = saved
    assert post(client, "/checkout/place").status_code == 302
    with test_app.app_context():
        assert db.session.scalar(select(Order)) is None


def test_invalid_shop_file_configuration_payment_and_csrf(client, test_app):
    owner, shop_id, file_id = setup(client, test_app)
    foreign_id = file(test_app, student(test_app, "foreign@school.edu"), configured=False)
    assert post(client, "/checkout/upload", {"file_id": str(foreign_id)}).status_code == 400
    assert post(client, "/checkout/upload", {"file_id": str(file_id)}).status_code == 302
    assert post(client, "/checkout/shop", {"shop_id": "99999"}).status_code == 400
    assert post(client, "/checkout/shop", {
        "shop_id": str(shop_id), "file_id": str(file_id), f"paper_size_{file_id}": "A4",
        f"color_mode_{file_id}": "GRAYSCALE", f"quantity_{file_id}": "0", **pickup_fields(),
    }).status_code == 400
    assert client.get("/checkout/payment").status_code == 302
    assert start(client, shop_id, file_id).status_code == 302
    assert post(client, "/checkout/payment", {"payment_method": "FAKE"}).status_code == 400
    assert post(client, "/checkout/payment", {"payment_method": "ONLINE"}).status_code == 400
    assert client.post("/checkout/place", data={}).status_code == 400
    with test_app.app_context():
        assert db.session.scalar(select(Order)) is None


def test_upload_multiple_files_and_remove_from_draft(client, test_app):
    owner, shop_id, first = setup(client, test_app)
    response = client.post("/checkout/upload/files", data={
        "csrf_token": token(client.get("/checkout/upload")),
        "files": [(BytesIO(PDF), "one.pdf"), (BytesIO(PDF), "two.pdf")],
    }, content_type="multipart/form-data")
    assert response.status_code == 302
    with test_app.app_context():
        from app.models import UploadedFile
        files = db.session.scalars(select(UploadedFile).where(UploadedFile.user_id == owner)).all()
        assert len(files) == 3
        selected = [item.id for item in files if item.id != first]
    assert post(client, "/checkout/upload", {"file_id": [str(value) for value in selected]}).status_code == 302
    data = {"file_id": [str(value) for value in selected], **pickup_fields()}
    for value in selected:
        data.update({f"paper_size_{value}": "A4", f"color_mode_{value}": "GRAYSCALE", f"quantity_{value}": "1"})
    assert post(client, "/checkout/shop", {"shop_id": str(shop_id), **data}).status_code == 302
    assert post(client, "/checkout/fulfillment", pickup_fields()).status_code == 302
    assert post(client, "/checkout/payment", {"payment_method": "ONSITE"}).status_code == 302
    assert post(client, "/checkout/place").status_code == 302
    with test_app.app_context():
        assert {item.uploaded_file_id for item in db.session.scalar(select(Order)).items} == set(selected)


def test_pdf_upload_counts_pages_and_rejects_malformed_pdf(client, test_app):
    owner = student(test_app)
    sign_in(client, owner)
    response = client.post("/checkout/upload/files", data={
        "csrf_token": token(client.get("/checkout/upload")),
        "files": (BytesIO(pdf_bytes(5)), "five-pages.pdf"),
    }, content_type="multipart/form-data")
    assert response.status_code == 302
    with test_app.app_context():
        record = db.session.scalar(select(UploadedFile).where(UploadedFile.user_id == owner))
        assert record.pdf_page_count == 5

    malformed = client.post("/checkout/upload/files", data={
        "csrf_token": token(client.get("/checkout/upload")),
        "files": (BytesIO(b"%PDF-1.7\\ninvalid page tree\\n%%EOF"), "broken.pdf"),
    }, content_type="multipart/form-data")
    assert malformed.status_code == 400
    assert b"Unable to read this PDF" in malformed.data
    with test_app.app_context():
        assert db.session.scalar(select(UploadedFile).where(UploadedFile.original_filename == "broken.pdf")) is None


def test_quote_refreshes_stale_staged_pdf_page_count(test_app):
    owner = student(test_app)
    shop_id = shop(test_app)
    data = pdf_bytes(2)
    with test_app.app_context():
        key = LocalStorage(test_app.config["UPLOAD_STORAGE_ROOT"], test_app.static_folder).save(data, "pdf")
        record = UploadedFile(
            user_id=owner, original_filename="two-pages.pdf", stored_filename=key,
            storage_key=key, mime_type="application/pdf", file_extension="pdf",
            file_size=len(data), sha256=hashlib.sha256(data).hexdigest(), pdf_page_count=1,
        )
        db.session.add(record)
        db.session.flush()
        db.session.add(PrintConfiguration(file_id=record.id, paper_size=PaperSize.A4,
                                          color_mode=ColorMode.GRAYSCALE, quantity=1, is_rush=False))
        db.session.commit()
        quote = quote_cart(user_id=owner, file_ids=[record.id], shop_id=shop_id,
                           max_quantity=999, max_files=20)
        assert quote.items[0].pdf_page_count == 2
        assert record.pdf_page_count == 2


def test_order_service_rechecks_stored_pdf_page_count(client, test_app):
    owner = student(test_app)
    shop_id = shop(test_app)
    file_id = file(test_app, owner)
    with test_app.app_context():
        quote = quote_cart(user_id=owner, file_ids=[file_id], shop_id=shop_id,
                           max_quantity=999, max_files=20)
        db.session.get(UploadedFile, file_id).pdf_page_count = 5
        db.session.commit()
        with pytest.raises(FulfillmentError, match="page count changed"):
            from app.services.orders import create_order
            create_order(quote)
        assert db.session.scalar(select(Order)) is None


def test_legacy_doc_without_page_count_cannot_be_underpriced(test_app):
    owner = student(test_app)
    shop_id = shop(test_app)
    data = bytes.fromhex("d0cf11e0a1b11ae1") + b"legacy document"
    with test_app.app_context():
        key = LocalStorage(test_app.config["UPLOAD_STORAGE_ROOT"], test_app.static_folder).save(data, "doc")
        record = UploadedFile(
            user_id=owner, original_filename="handout.doc", stored_filename=key,
            storage_key=key, mime_type="application/msword", file_extension="doc",
            file_size=len(data), sha256=hashlib.sha256(data).hexdigest(),
        )
        db.session.add(record)
        db.session.flush()
        db.session.add(PrintConfiguration(file_id=record.id, paper_size=PaperSize.A4,
                                          color_mode=ColorMode.GRAYSCALE, quantity=3, is_rush=False))
        db.session.commit()
        with pytest.raises(PricingError, match="Export it as a PDF"):
            quote_cart(user_id=owner, file_ids=[record.id], shop_id=shop_id,
                       max_quantity=999, max_files=20)


def test_word_without_renderer_shows_unavailable_count_and_blocks_checkout(monkeypatch, client, test_app):
    monkeypatch.setattr("app.storage.validation.shutil.which", lambda name: None)
    owner = student(test_app)
    shop_id = shop(test_app)
    sign_in(client, owner)
    client.get(f"/checkout/upload?shop_id={shop_id}")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", '<Types><Override ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr("docProps/app.xml", "<Properties><Pages>1</Pages></Properties>")
    response = client.post("/checkout/upload/files", data={
        "csrf_token": token(client.get("/checkout/upload")),
        "files": (BytesIO(buffer.getvalue()), "two-pages.docx"),
    }, content_type="multipart/form-data")
    assert response.status_code == 302
    page = client.get("/checkout/shop")
    assert page.status_code == 200
    assert b"Unable to determine" in page.data
    assert b"Page count unavailable" in page.data
    assert b' data-quote-valid="false"' in page.data
    assert b"Export it as a PDF" in page.data


def test_docx_page_count_is_used_for_page_based_pricing(test_app):
    owner = student(test_app)
    shop_id = shop(test_app)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", '<Types><Override ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr("docProps/app.xml", "<Properties><Pages>4</Pages></Properties>")
    data = buffer.getvalue()
    with test_app.app_context():
        key = LocalStorage(test_app.config["UPLOAD_STORAGE_ROOT"], test_app.static_folder).save(data, "docx")
        record = UploadedFile(
            user_id=owner, original_filename="handout.docx", stored_filename=key,
            storage_key=key, mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            file_extension="docx", file_size=len(data), sha256=hashlib.sha256(data).hexdigest(),
            pdf_page_count=4,
        )
        db.session.add(record)
        db.session.flush()
        db.session.add(PrintConfiguration(file_id=record.id, paper_size=PaperSize.A4,
                                          color_mode=ColorMode.GRAYSCALE, quantity=3, is_rush=False))
        db.session.commit()
        quote = quote_cart(user_id=owner, file_ids=[record.id], shop_id=shop_id,
                           max_quantity=999, max_files=20)
        item = quote.items[0]
        assert item.pdf_page_count == 4
        assert item.total_printed_pages == 12
        assert item.line_total == Decimal("27.00")


def test_page_based_price_and_snapshots_are_server_authoritative_for_multiple_files(client, test_app):
    owner = student(test_app)
    shop_id = shop(test_app)
    with test_app.app_context():
        db.session.add_all([
            PrintPrice(shop_id=shop_id, paper_size=PaperSize.A4, color_mode=ColorMode.COLOR, price=Decimal("5.00")),
            PrintPrice(shop_id=shop_id, paper_size=PaperSize.LETTER, color_mode=ColorMode.GRAYSCALE, price=Decimal("2.00")),
        ])
        db.session.commit()
    sign_in(client, owner)
    uploaded = client.post("/checkout/upload/files", data={
        "csrf_token": token(client.get("/checkout/upload")),
        "files": [(BytesIO(pdf_bytes(5)), "resume.pdf"), (BytesIO(pdf_bytes(8)), "portfolio.pdf")],
    }, content_type="multipart/form-data")
    assert uploaded.status_code == 302
    with test_app.app_context():
        records = db.session.scalars(select(UploadedFile).where(UploadedFile.user_id == owner)
                                     .order_by(UploadedFile.id)).all()
        first, second = records
        assert [first.pdf_page_count, second.pdf_page_count] == [5, 8]
        first_id, second_id = first.id, second.id
    assert post(client, "/checkout/upload", {"file_id": [str(first_id), str(second_id)]}).status_code == 302
    quote = client.post("/checkout/shop", data={
        "csrf_token": token(client.get("/checkout/upload")),
        "intent": "quote", "shop_id": str(shop_id), "file_id": [str(first_id), str(second_id)],
        f"paper_size_{first_id}": "A4", f"color_mode_{first_id}": "COLOR", f"quantity_{first_id}": "2",
        f"paper_size_{second_id}": "LETTER", f"color_mode_{second_id}": "GRAYSCALE", f"quantity_{second_id}": "1",
        f"pdf_page_count_{first_id}": "1", f"total_printed_pages_{first_id}": "1",
        "total": "0.01", "unit_price": "0.01",
    }, headers={"Accept": "application/json"})
    assert quote.status_code == 200
    assert quote.json["subtotal"] == "66.00"
    assert quote.json["total"] == "66.00"
    copies_three = client.post("/checkout/shop", data={
        "csrf_token": token(client.get("/checkout/upload")),
        "intent": "quote", "shop_id": str(shop_id), "file_id": [str(first_id), str(second_id)],
        f"paper_size_{first_id}": "A4", f"color_mode_{first_id}": "COLOR", f"quantity_{first_id}": "3",
        f"paper_size_{second_id}": "LETTER", f"color_mode_{second_id}": "GRAYSCALE", f"quantity_{second_id}": "1",
        f"pdf_page_count_{first_id}": "0", f"price_{first_id}": "0.01", "total": "0.01",
    }, headers={"Accept": "application/json"})
    assert copies_three.status_code == 200
    assert copies_three.json["subtotal"] == "91.00"

    settings = {"shop_id": str(shop_id), "file_id": [str(first_id), str(second_id)],
                **pickup_fields()}
    settings.update({f"paper_size_{first_id}": "A4", f"color_mode_{first_id}": "COLOR", f"quantity_{first_id}": "2",
                     f"paper_size_{second_id}": "LETTER", f"color_mode_{second_id}": "GRAYSCALE", f"quantity_{second_id}": "1"})
    assert post(client, "/checkout/shop", settings).status_code == 302
    assert post(client, "/checkout/fulfillment", pickup_fields()).status_code == 302
    assert post(client, "/checkout/payment", {"payment_method": "ONSITE"}).status_code == 302
    assert post(client, "/checkout/place", {"total": "0.01", "pdf_page_count": "1"}).status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order).where(Order.user_id == owner))
        assert order.subtotal == order.total == Decimal("66.00")
        items = sorted(order.items, key=lambda item: item.uploaded_file_id)
        assert [(item.pdf_page_count, item.quantity, item.total_printed_pages, item.line_total)
                for item in items] == [
                    (5, 2, 10, Decimal("50.00")),
                    (8, 1, 8, Decimal("16.00")),
                ]
    detail = client.get(f"/orders/{order.order_reference}")
    assert b"Total Printed Pages" in detail.data


@pytest.mark.parametrize("confirmation_stage", ("before_processing", "after_delivery"))
def test_professor_self_delivery_allows_cash_at_faculty(client, test_app, confirmation_stage):
    owner_id, shop_id, file_id = setup(client, test_app, professor=True, online=True)
    professor_id = approved_professor(test_app, name="Verified Teacher")
    with test_app.app_context():
        from app.models import User, Professor, ProfessorVerificationStatus
        user = db.session.scalar(select(User).where(User.email == "student@example.com"))
        linked = db.session.get(Professor, professor_id)
        other = db.session.scalar(select(User).where(User.professor_id == professor_id))
        other.professor = None
        db.session.flush()
        user.professor = linked
        user.professor_department = linked.faculty
        user.professor_verification_status = ProfessorVerificationStatus.VERIFIED
        db.session.commit()
    offer_professor_service(test_app, shop_id)
    assert start(client, shop_id, file_id, destination={"destination": "PROFESSOR"}).status_code == 302
    assert post(client, "/checkout/payment", {"payment_method": "ONSITE"}).status_code == 302
    assert post(client, "/checkout/place").status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert order.professor_recipient_type == "SELF"
        assert order.payment.payment_method == PaymentMethod.ONSITE
        assert order.payment.payment_status == PaymentStatus.PENDING
        reference = order.order_reference
        payment_id = order.payment.id
    staff_id = student(test_app, "faculty-cash-staff@example.edu", role=UserRole.SHOP_STAFF)
    with test_app.app_context():
        from app.models import User
        db.session.get(User, staff_id).shop_id = shop_id
        db.session.commit()
    sign_in(client, staff_id)
    staff_url = f"/staff/orders/{reference}"
    from test_staff_orders import action_post
    dashboard = client.get("/shop")
    assert b"<strong>1</strong><span>Payment actions</span>" in dashboard.data
    assert reference.encode() in client.get("/payments/verification").data
    review = client.get(f"/payments/verification/{payment_id}")
    assert b"Confirm Faculty cash received" in review.data
    if confirmation_stage == "before_processing":
        assert client.post(f"/payments/verification/{payment_id}/confirm-onsite", data={
            "csrf_token": token(review), "cash_received": "yes",
        }).status_code == 302
        with test_app.app_context():
            order = db.session.scalar(select(Order))
            assert order.status.value == "PROCESSING" and order.payment.payment_status == PaymentStatus.PAID
    else:
        assert action_post(client, staff_url, "start_processing").status_code == 302
    assert action_post(client, staff_url, "mark_ready").status_code == 302
    assert action_post(client, staff_url, "mark_delivered").status_code == 302
    assert action_post(client, staff_url, "complete_professor").status_code == 409
    if confirmation_stage == "after_delivery":
        review = client.get(f"/payments/verification/{payment_id}")
        assert client.post(f"/payments/verification/{payment_id}/confirm-onsite", data={
            "csrf_token": token(review), "cash_received": "yes",
        }).status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert order.status.value == "DELIVERED" and order.payment.payment_status == PaymentStatus.PAID
    sign_in(client, owner_id)
    owner_page = client.get(f"/orders/{reference}")
    assert b"Complete order" in owner_page.data
    assert client.post(f"/orders/{reference}/complete", data={"csrf_token": token(owner_page)}).status_code == 302


def test_student_professor_delivery_and_professor_normal_order(client, test_app):
    _, shop_id, file_id = setup(client, test_app, online=True)
    professor_id = approved_professor(test_app)
    offer_professor_service(test_app, shop_id)
    assert start(client, shop_id, file_id, destination={
        "destination": "PROFESSOR", "professor_id": str(professor_id),
    }).status_code == 302
    assert post(client, "/checkout/payment", {"payment_method": "ONSITE"}).status_code == 400
    assert post(client, "/checkout/payment", {"payment_method": "ONLINE"}).status_code == 400
    assert post(client, "/checkout/payment", {"payment_method": "ONLINE", "payment_reference": "STUDENT-1234"}).status_code == 302
    assert post(client, "/checkout/place").status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert order.professor_id == professor_id
        assert order.professor_name == "Maria Santos"
        assert order.payment.payment_method == PaymentMethod.ONLINE

    professor_user = student(test_app, "unverified@example.edu", UserRole.PROFESSOR)
    sign_in(client, professor_user)
    professor_file = upload_checkout_file(client, test_app, professor_user, "professor.pdf")
    assert start(client, shop_id, professor_file).status_code == 302
    assert post(client, "/checkout/payment", {"payment_method": "ONSITE"}).status_code == 302
    assert post(client, "/checkout/place").status_code == 302
    with test_app.app_context():
        orders = db.session.scalars(select(Order).order_by(Order.id)).all()
        assert len(orders) == 2 and orders[1].user_id == professor_user
        assert orders[1].payment.payment_method == PaymentMethod.ONSITE


def test_review_rechecks_database_price_before_placement(client, test_app):
    _, shop_id, file_id = setup(client, test_app)
    assert start(client, shop_id, file_id).status_code == 302
    assert post(client, "/checkout/payment", {"payment_method": "ONSITE"}).status_code == 302
    with test_app.app_context():
        rate = db.session.scalar(select(PrintPrice).where(PrintPrice.shop_id == shop_id))
        rate.price = Decimal("9.00")
        db.session.commit()
    changed = post(client, "/checkout/place", {"total": "4.50"})
    assert changed.status_code == 409
    assert b"PHP 18.00" in changed.data
    assert b'class="order-print-transition"' not in changed.data
    with test_app.app_context():
        assert db.session.scalar(select(Order)) is None
    placed = post(client, "/checkout/place")
    assert placed.status_code == 302
    with test_app.app_context():
        assert db.session.scalar(select(Order)).total == Decimal("18.00")


def test_legacy_library_file_cannot_enter_new_checkout(client, test_app):
    owner, shop_id, _ = setup(client, test_app)
    existing = file(test_app, owner, name="Saved.pdf", configured=True, quantity=3)
    assert post(client, "/checkout/upload", {"file_id": str(existing)}).status_code == 400
    with test_app.app_context():
        assert db.session.get(UploadedFile, existing).configuration.quantity == 3
        assert db.session.scalar(select(Order)) is None
