"""Blue and Silver physical professor delivery boundaries."""

from sqlalchemy import select

from app.extensions import db
from app.models import Order, Payment, Professor, ProfessorVerificationStatus, User, UserRole
from app.services.professors import professor_service_available
from test_orders import (approved_professor, file, offer_professor_service,
                         professor_place, professor_review, shop, sign_in,
                         student, token)


def test_student_consent_and_shop_are_enforced_on_forged_requests(client, test_app):
    owner = student(test_app)
    blue = shop(test_app, name="Blue and Silver Bookstore")
    other = shop(test_app, name="Iced Design and Prints")
    file_id = file(test_app, owner)
    offer_professor_service(test_app, blue)
    offer_professor_service(test_app, other)  # Stale/forged service record cannot grant eligibility.
    accepted = approved_professor(test_app)
    declined = approved_professor(test_app, accepts=False, name="Declined Professor")
    sign_in(client, owner)
    listing = client.get("/orders/new", query_string={"shop_id": blue})
    assert b"Deliver to Professor" in listing.data
    assert b"Maria Santos" in listing.data
    assert b"Declined Professor" not in listing.data
    assert professor_review(client, file_id, blue, accepted).status_code == 200
    assert professor_review(client, file_id, blue, declined).status_code == 400
    assert professor_place(client, file_id, blue, declined).status_code == 400
    assert professor_review(client, file_id, other, accepted).status_code == 400
    assert professor_place(client, file_id, other, accepted).status_code == 400
    with test_app.app_context():
        assert professor_service_available(blue)
        assert not professor_service_available(other)
        assert db.session.scalar(select(Order)) is None


def test_professor_self_delivery_and_setting_do_not_expose_dropdown(client, test_app):
    blue = shop(test_app, name="Blue and Silver Bookstore")
    other = shop(test_app, name="CHALECOSPOT")
    offer_professor_service(test_app, blue)
    offer_professor_service(test_app, other)
    profile_id = approved_professor(test_app, accepts=False, linked=False)
    account_id = student(test_app, "maria.santos@example.edu", role=UserRole.PROFESSOR)
    with test_app.app_context():
        db.session.get(User, account_id).professor_id = profile_id
        db.session.get(User, account_id).professor_verification_status = ProfessorVerificationStatus.VERIFIED
        db.session.commit()
    file_id = file(test_app, account_id)
    sign_in(client, account_id)
    selection = client.get("/orders/new", query_string={"shop_id": blue})
    assert b"Deliver to Faculty" in selection.data
    assert b'id="professor_id"' not in selection.data
    assert b"Engineering Building 204" in selection.data
    assert client.get("/professor/settings").status_code == 200
    assert client.get("/orders/new", query_string={
        "file_id": file_id, "shop_id": other, "destination": "PROFESSOR"
    }).status_code == 400
    forged = client.get("/orders/new", query_string={
        "file_id": file_id, "shop_id": blue, "destination": "PROFESSOR", "professor_id": profile_id,
    })
    assert forged.status_code == 400
    reviewed = client.get("/orders/new", query_string={
        "file_id": file_id, "shop_id": blue, "destination": "PROFESSOR",
    })
    assert reviewed.status_code == 200
    assert b"Deliver to Faculty" in reviewed.data
    placed = client.post("/orders/create", data={
        "csrf_token": token(reviewed), "file_id": file_id, "shop_id": blue,
        "destination": "PROFESSOR",
    })
    assert placed.status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert (order.professor_id, order.professor_recipient_type) == (profile_id, "SELF")
        assert order.professor_name == "Maria Santos"
        assert db.session.get(Professor, profile_id).accepts_student_deliveries is False
        db.session.get(Professor, profile_id).name = "Changed Later"
        db.session.get(User, account_id).professor_verification_status = ProfessorVerificationStatus.REJECTED
        db.session.commit()
    detail = client.get(placed.headers["Location"])
    assert b"Maria Santos" in detail.data and b"Changed Later" not in detail.data
    assert client.get("/orders").status_code == 200
    paid_later = client.post(placed.headers["Location"] + "/payment", data={
        "csrf_token": token(detail), "payment_method": "ONSITE",
    })
    assert paid_later.status_code == 400
    with test_app.app_context():
        assert db.session.scalar(select(Payment)) is None


def test_professor_can_toggle_student_delivery_consent(client, test_app):
    profile_id = approved_professor(test_app, accepts=False, linked=False)
    account_id = student(test_app, "maria.santos@example.edu", role=UserRole.PROFESSOR)
    with test_app.app_context():
        db.session.get(User, account_id).professor_id = profile_id
        db.session.get(User, account_id).professor_verification_status = ProfessorVerificationStatus.VERIFIED
        db.session.commit()
    sign_in(client, account_id)
    page = client.get("/professor/settings")
    assert page.status_code == 200
    assert client.post("/professor/settings", data={"accepts_student_deliveries": "y"}).status_code == 400
    assert client.post("/professor/settings", data={
        "csrf_token": token(page), "accepts_student_deliveries": "y"
    }).status_code == 302
    with test_app.app_context():
        assert db.session.get(Professor, profile_id).accepts_student_deliveries is True
    assert client.post("/professor/settings", data={
        "csrf_token": token(client.get("/professor/settings"))
    }).status_code == 302
    with test_app.app_context():
        assert db.session.get(Professor, profile_id).accepts_student_deliveries is False


def test_professor_provisioning_requires_linked_matching_profile(test_app):
    profile_id = approved_professor(test_app, accepts=False, linked=False)
    runner = test_app.test_cli_runner()
    options = ["create-privileged-user", "--role", "PROFESSOR", "--professor-id", str(profile_id),
               "--name", "Maria Santos", "--email", "maria.santos@example.edu"]
    result = runner.invoke(args=options, input="A-strong-password-123\nA-strong-password-123\n")
    assert result.exit_code == 0, result.output
    with test_app.app_context():
        user = db.session.scalar(select(User).where(User.role == UserRole.PROFESSOR))
        assert user.professor_id == profile_id
    duplicate = runner.invoke(args=options, input="A-strong-password-123\nA-strong-password-123\n")
    assert duplicate.exit_code != 0


def test_blue_staff_can_enable_and_disable_student_deliveries(client, test_app):
    admin_id = student(test_app, "blue@example.edu", role=UserRole.SHOP_STAFF)
    blue_id = shop(test_app, name="Blue and Silver Bookstore")
    with test_app.app_context():
        db.session.get(User, admin_id).shop_id = blue_id
        db.session.commit()
    profile_id = approved_professor(test_app, accepts=False, linked=False)
    sign_in(client, admin_id)
    path = f"/admin/professors/{profile_id}/edit"
    assert b"Off" in client.get("/admin/professors").data
    fields = {
        "name": "Maria Santos", "email": "maria.santos@example.edu",
        "department": "Computer Engineering", "office": "Engineering Building 204",
        "faculty": "MITL", "account_id": "0",
        "is_active": "y", "direct_send_approved": "y",
    }
    assert client.post(path, data={
        **fields, "csrf_token": token(client.get(path)),
        "accepts_student_deliveries": "y",
    }).status_code == 302
    with test_app.app_context():
        assert db.session.get(Professor, profile_id).accepts_student_deliveries is True
    assert b"On" in client.get("/admin/professors").data
    assert client.post(path, data={
        **fields, "csrf_token": token(client.get(path)),
    }).status_code == 302
    with test_app.app_context():
        assert db.session.get(Professor, profile_id).accepts_student_deliveries is False


def test_non_blue_admin_service_toggle_is_rejected(client, test_app):
    admin_id = student(test_app, "admin@example.edu", role=UserRole.ADMIN)
    other = shop(test_app, name="Pixels Print and Press")
    sign_in(client, admin_id)
    path = f"/admin/shops/{other}/services"
    editor = client.get(f"/admin/shops/{other}/edit")
    assert b'<option value="DIRECT_TO_PROFESSOR"' not in editor.data
    response = client.post(path, data={
        "csrf_token": token(editor), "service_type": "DIRECT_TO_PROFESSOR", "enabled": "y",
    })
    assert response.status_code == 400
    with test_app.app_context():
        assert not professor_service_available(other)
