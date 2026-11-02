"""Only Blue and Silver can create manual Student-to-Professor recipients."""

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import Order, Professor, User, UserRole
from app.services.professors import selectable_professors
from test_orders import file, offer_professor_service, professor_place, professor_review, shop, sign_in, student, token
from test_professor_management_deletion import blue_staff
from test_shop_availability import staff_for


def details(**changes):
    return {"name": "Professor Directory", "email": "directory@example.edu", "department": "MITL",
            "faculty": "Computer Engineering", "office": "Faculty Office 123", "is_active": "y",
            "direct_send_approved": "y", "accepts_student_deliveries": "y", **changes}


def save(client, path="/admin/professors/new", **changes):
    return client.post(path, data={"csrf_token": token(client.get(path)), **details(**changes)})


def test_staff_entered_recipient_can_receive_student_orders_without_a_login(client, test_app):
    blue, staff = blue_staff(test_app)
    sign_in(client, staff)
    assert b">Add professor</a>" in client.get("/admin/professors").data
    assert client.post("/admin/professors/new", data=details()).status_code == 400
    assert save(client).status_code == 302
    profile = db.session.scalar(select(Professor))
    assert profile.account is None and profile.is_staff_managed
    assert db.session.scalar(select(User).where(User.email == "directory@example.edu")) is None
    assert [item.id for item in selectable_professors()] == [profile.id]
    edit = f"/admin/professors/{profile.id}/edit"
    assert b"Faculty Office 123" in client.get(edit).data
    owner = student(test_app)
    document = file(test_app, owner)
    sign_in(client, owner)
    assert b"Professor Directory" in client.get("/orders/new").data
    assert professor_review(client, document, blue, profile.id).status_code == 200
    assert professor_place(client, document, blue, profile.id).status_code == 302
    order = db.session.scalar(select(Order))
    assert order.professor_office == "Faculty Office 123"
    assert order.professor_faculty == "Computer Engineering"
    sign_in(client, staff)
    assert save(client, edit, name="Changed Recipient", office="New Location").status_code == 302
    db.session.refresh(order)
    assert order.professor_name == "Professor Directory" and order.professor_office == "Faculty Office 123"
    assert save(client, edit, accepts_student_deliveries="").status_code == 302
    assert selectable_professors() == []


@pytest.mark.parametrize("changes", [
    {"email": "invalid"}, {"name": " "}, {"office": ""}, {"faculty": "Psychology"},
    {"department": "forged"}, {"email": "existing@example.edu"},
])
def test_invalid_or_existing_account_details_do_not_create_recipients(client, test_app, changes):
    _, staff = blue_staff(test_app)
    student(test_app, "existing@example.edu", UserRole.PROFESSOR)
    sign_in(client, staff)
    response = save(client, **changes)
    assert response.status_code == 200
    assert b'class="field-error"' in response.data
    assert db.session.scalar(select(Professor)) is None


def test_duplicate_email_does_not_overwrite_existing_recipient(client, test_app):
    _, staff = blue_staff(test_app)
    sign_in(client, staff)
    assert save(client).status_code == 302
    assert save(client, name="Duplicate", email="DIRECTORY@example.edu").status_code == 200
    profiles = db.session.scalars(select(Professor)).all()
    assert len(profiles) == 1 and profiles[0].name == "Professor Directory"


@pytest.mark.parametrize("role", [UserRole.STUDENT, UserRole.PROFESSOR, UserRole.ADMIN, UserRole.SHOP_STAFF])
def test_other_accounts_cannot_create_manual_professor(client, test_app, role):
    other = shop(test_app, name="Other Shop")
    actor = staff_for(test_app, other, "other@example.edu") if role == UserRole.SHOP_STAFF else student(test_app, role=role)
    sign_in(client, actor)
    assert client.get("/admin/professors/new").status_code == 403
    page = client.get("/shop" if role == UserRole.SHOP_STAFF else "/admin" if role == UserRole.ADMIN else "/professor" if role == UserRole.PROFESSOR else "/student")
    assert client.post("/admin/professors/new", data={"csrf_token": token(page), **details()}).status_code == 403
    assert db.session.scalar(select(Professor)) is None
