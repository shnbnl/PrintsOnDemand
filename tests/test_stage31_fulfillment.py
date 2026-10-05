"""Conditional faculty delivery and managed-profile checkout rules."""

from sqlalchemy import select

from app.extensions import db
from app.models import Order, Professor, ProfessorVerificationStatus, User
from test_checkout_flow import print_fields, post, setup
from test_fulfillment import delivery_fields, offer_delivery
from test_orders import approved_professor, offer_professor_service, pickup_fields, shop


def configure(file_id, **fulfillment):
    return fulfillment


def select_shop(client, file_id, shop_id):
    assert post(client, "/checkout/upload", {"file_id": str(file_id)}).status_code == 302
    assert post(client, "/checkout/shop", {"shop_id": str(shop_id), **print_fields(file_id)}).status_code == 302
    return client.get("/checkout/fulfillment")


def test_student_professor_option_only_at_blue_and_managed_faculty_is_immutable(client, test_app):
    _, blue, file_id = setup(client, test_app, online=True)
    offer_professor_service(test_app, blue)
    eligible = approved_professor(test_app, faculty="CCIS", name="Eligible Professor")
    approved_professor(test_app, accepts=False, name="Not Accepting")
    for name in ("CHALECOSPOT", "Iced Design and Prints", "Pixels Print and Press"):
        other = shop(test_app, name=name)
        page = select_shop(client, file_id, other)
        assert b'Deliver to Professor' not in page.data
        assert b'id="professor_id"' not in page.data
        assert post(client, "/checkout/fulfillment", configure(
            file_id, destination="PROFESSOR", professor_id=str(eligible),
        )).status_code == 400
    page = select_shop(client, file_id, blue)
    assert b'Deliver to Professor' in page.data
    assert b'Eligible Professor' in page.data and b'Not Accepting' not in page.data
    assert b'data-faculty="CCIS"' in page.data
    assert b'name="professor_faculty"' not in page.data
    assert post(client, "/checkout/fulfillment", configure(
        file_id, destination="PROFESSOR", professor_id=str(eligible), professor_faculty="GE",
    )).status_code == 400
    assert post(client, "/checkout/fulfillment", configure(
        file_id, destination="PROFESSOR", professor_id="999999",
    )).status_code == 400
    assert post(client, "/checkout/fulfillment", configure(
        file_id, destination="PROFESSOR", professor_id=str(eligible),
    )).status_code == 302
    assert post(client, "/checkout/payment", {"payment_method": "ONSITE"}).status_code == 400
    assert post(client, "/checkout/payment", {"payment_method": "ONLINE"}).status_code == 400
    assert post(client, "/checkout/payment", {"payment_method": "ONLINE", "payment_reference": "STUDENT-1234"}).status_code == 302
    assert post(client, "/checkout/place").status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert (order.professor_id, order.professor_faculty, order.professor_recipient_type) == (
            eligible, "CCIS", "STUDENT_SELECTED",
        )
        db.session.get(Professor, eligible).faculty = "GE"
        db.session.commit()
        assert db.session.get(Order, order.id).professor_faculty == "CCIS"


def test_student_shop_change_resets_professor_delivery(client, test_app):
    _, blue, file_id = setup(client, test_app, online=True)
    offer_professor_service(test_app, blue)
    professor_id = approved_professor(test_app)
    other = shop(test_app, name="CHALECOSPOT")
    select_shop(client, file_id, blue)
    assert post(client, "/checkout/fulfillment", configure(
        file_id, destination="PROFESSOR", professor_id=str(professor_id),
    )).status_code == 302
    assert post(client, "/checkout/shop", {"shop_id": str(other), **print_fields(file_id)}).status_code == 302
    page = client.get("/checkout/fulfillment")
    assert b'Deliver to Professor' not in page.data
    assert client.get("/checkout/payment").headers["Location"].endswith("/checkout/fulfillment")
    assert post(client, "/checkout/fulfillment", configure(
        file_id, destination="PROFESSOR", professor_id=str(professor_id),
    )).status_code == 400


def test_professor_pickup_and_faculty_destination_use_managed_profile(client, test_app):
    owner, blue, file_id = setup(client, test_app, professor=True, online=True)
    offer_professor_service(test_app, blue)
    managed = approved_professor(test_app, faculty="CCIS", linked=False)
    with test_app.app_context():
        account = db.session.get(User, owner)
        account.professor_id = managed
        account.professor_verification_status = ProfessorVerificationStatus.VERIFIED
        account.professor_department = "MITL"  # Registration data is not authoritative.
        db.session.commit()
    page = select_shop(client, file_id, blue)
    assert b'Scheduled Pickup' in page.data and b'Deliver to Faculty' in page.data
    assert b'Deliver to Professor' not in page.data and b'id="professor_id"' not in page.data
    assert b'<strong>CCIS</strong>' in page.data and b'name="professor_faculty"' not in page.data
    assert post(client, "/checkout/fulfillment", configure(
        file_id, destination="PROFESSOR", professor_faculty="MITL",
    )).status_code == 400
    assert post(client, "/checkout/fulfillment", configure(
        file_id, destination="PROFESSOR", professor_id=str(managed),
    )).status_code == 400
    assert post(client, "/checkout/fulfillment", configure(file_id, destination="PROFESSOR")).status_code == 302
    assert post(client, "/checkout/payment", {"payment_method": "ONSITE"}).status_code == 400
    assert post(client, "/checkout/payment", {"payment_method": "ONLINE"}).status_code == 400
    assert post(client, "/checkout/payment", {"payment_method": "ONLINE", "payment_reference": "FACULTY-1234"}).status_code == 302
    assert post(client, "/checkout/place").status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert (order.professor_id, order.professor_faculty, order.professor_recipient_type) == (
            managed, "CCIS", "SELF",
        )
        db.session.get(Professor, managed).faculty = "GE"
        db.session.commit()
        assert db.session.get(Order, order.id).professor_faculty == "CCIS"


def test_professor_unverified_unlinked_or_inactive_profile_cannot_deliver_to_faculty(client, test_app):
    owner, blue, file_id = setup(client, test_app, professor=True)
    offer_professor_service(test_app, blue)
    managed = approved_professor(test_app, linked=False)
    select_shop(client, file_id, blue)
    for linked, verified, active in (
        (False, False, True), (True, False, True), (True, True, False),
    ):
        with test_app.app_context():
            account = db.session.get(User, owner)
            account.professor_id = managed if linked else None
            account.professor_verification_status = (
                ProfessorVerificationStatus.VERIFIED if verified else ProfessorVerificationStatus.PENDING
            )
            db.session.get(Professor, managed).is_active = active
            db.session.commit()
        page = client.get("/checkout/fulfillment")
        assert b'Scheduled Pickup' in page.data and b'Deliver to Faculty' not in page.data
        assert post(client, "/checkout/fulfillment", configure(file_id, destination="PROFESSOR")).status_code == 400
    with test_app.app_context():
        db.session.get(User, owner).professor_verification_status = ProfessorVerificationStatus.VERIFIED
        db.session.get(Professor, managed).is_active = True
        db.session.get(Professor, managed).faculty = None
        db.session.commit()
    assert b'Deliver to Faculty' not in client.get("/checkout/fulfillment").data
    assert post(client, "/checkout/fulfillment", configure(file_id, **pickup_fields())).status_code == 302
    assert post(client, "/checkout/payment", {"payment_method": "ONSITE"}).status_code == 302


def test_professor_general_delivery_uses_shop_setting_and_preserves_csrf(client, test_app):
    _, blue, file_id = setup(client, test_app, professor=True)
    select_shop(client, file_id, blue)
    assert b'value="DELIVERY"' not in client.get("/checkout/fulfillment").data
    assert post(client, "/checkout/fulfillment", configure(
        file_id, **delivery_fields(),
    )).status_code == 400
    offer_delivery(test_app, blue)
    assert b'value="DELIVERY"' in client.get("/checkout/fulfillment").data
    assert post(client, "/checkout/fulfillment", configure(file_id, **delivery_fields())).status_code == 302
    assert client.post("/checkout/fulfillment", data=configure(file_id, **pickup_fields())).status_code == 400
