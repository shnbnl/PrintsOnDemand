"""Guided checkout: order, payment, file ownership, and fulfillment boundaries."""

from decimal import Decimal
from io import BytesIO

import pytest

from sqlalchemy import select

from app.extensions import db
from app.models import Order, PaymentMethod, PaymentStatus, PrintPrice, PrintingShop, UploadedFile, UserRole
from test_orders import (
    PDF, approved_professor, file, offer_professor_service, pickup_fields,
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
    assert b"PHP 4.50" in confirmation.data
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert order.user_id == owner and order.shop_id == shop_id
        assert order.order_reference.encode() in confirmation.data
        assert order.total == Decimal("4.50")
        assert [item.uploaded_file_id for item in order.items] == [file_id]
        assert order.payment.payment_method == PaymentMethod.ONSITE
        assert order.payment.payment_status == PaymentStatus.PENDING
    assert client.get("/orders").status_code == 200
    assert client.post("/checkout/place", data={"csrf_token": token(confirmation)}).headers["Location"] == placed.headers["Location"]
    with test_app.app_context():
        assert len(db.session.scalars(select(Order)).all()) == 1


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


def test_professor_self_delivery_requires_online(client, test_app):
    _, shop_id, file_id = setup(client, test_app, professor=True, online=True)
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
    assert post(client, "/checkout/payment", {"payment_method": "ONSITE"}).status_code == 400
    assert post(client, "/checkout/payment", {"payment_method": "ONLINE"}).status_code == 400
    assert post(client, "/checkout/payment", {"payment_method": "ONLINE", "payment_reference": "FACULTY-1234"}).status_code == 302
    assert post(client, "/checkout/place").status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert order.professor_recipient_type == "SELF"
        assert order.payment.payment_method == PaymentMethod.ONLINE


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
