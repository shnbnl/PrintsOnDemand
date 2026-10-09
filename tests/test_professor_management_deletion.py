"""Blue and Silver may delete professor records without losing other owners' order history."""

from sqlalchemy import select

from app.extensions import db
from app.models import Order, Professor, ProfessorVerificationStatus, UploadedFile, User, UserRole
from app.services.orders import create_order
from app.services.pricing import quote_order
from test_orders import (
    approved_professor, file, offer_professor_service, professor_place, professor_review, shop,
    sign_in, student, token,
)


def blue_staff(app):
    blue = shop(app, name="Blue and Silver Bookstore")
    offer_professor_service(app, blue)
    staff = student(app, "blue.staff@example.edu", UserRole.SHOP_STAFF)
    with app.app_context():
        db.session.get(User, staff).shop_id = blue
        db.session.commit()
    return blue, staff


def confirm_delete(client, path):
    page = client.get(path)
    assert page.status_code == 200
    return client.post(path, data={"csrf_token": token(page), "confirm_delete": "yes"})


def test_manage_verified_professor_returns_to_management_page(client, test_app):
    _, staff = blue_staff(test_app)
    account_id = student(test_app, "one@example.edu", UserRole.PROFESSOR)
    with test_app.app_context():
        account = db.session.get(User, account_id)
        account.name = "Professor One"
        account.professor_department = "CCIS"
        account.professor_faculty = "Computer Science"
        db.session.commit()
    sign_in(client, staff)
    page = client.get("/admin/professors")
    created = client.post(f"/admin/professors/accounts/{account_id}/verify", data={
        "csrf_token": token(page),
    })
    assert created.status_code == 302
    assert created.headers["Location"].endswith("/admin/professors")
    with test_app.app_context():
        profile_id = db.session.get(User, account_id).professor_id
    edit = f"/admin/professors/{profile_id}/edit"
    page = client.get(edit)
    saved = client.post(edit, data={
        "csrf_token": token(page), "name": "Professor Updated", "email": "forged@example.edu",
        "department": "MITL", "faculty": "Psychology", "is_active": "y",
        "direct_send_approved": "y", "accepts_student_deliveries": "y",
    })
    assert saved.status_code == 302
    assert saved.headers["Location"].endswith("/admin/professors")
    assert b"Professor One" in client.get(saved.headers["Location"]).data
    with test_app.app_context():
        profile = db.session.get(Professor, profile_id)
        assert (profile.department, profile.faculty, profile.email) == ("CCIS", "Computer Science", "one@example.edu")
        assert profile.is_active and profile.direct_send_approved and profile.accepts_student_deliveries


def test_linked_managed_profile_cannot_be_deleted_separately(client, test_app):
    blue, staff = blue_staff(test_app)
    profile_id = approved_professor(test_app, faculty="CCIS")
    with test_app.app_context():
        account_id = db.session.get(Professor, profile_id).account.id
    owner = student(test_app)
    document = file(test_app, owner)
    sign_in(client, owner)
    assert professor_review(client, document, blue, profile_id).status_code == 200
    placed = professor_place(client, document, blue, profile_id)
    assert placed.status_code == 302
    with test_app.app_context():
        order_id = db.session.scalar(select(Order.id))
    sign_in(client, staff)
    path = f"/admin/professors/{profile_id}/delete"
    management = client.get("/admin/professors")
    assert path.encode() not in management.data
    assert client.get(path).status_code == 404
    assert client.post(path, data={"csrf_token": token(management), "confirm_delete": "yes"}).status_code == 404
    with test_app.app_context():
        assert db.session.get(Professor, profile_id) is not None
    with test_app.app_context():
        assert db.session.get(Professor, profile_id) is not None
        account = db.session.get(User, account_id)
        assert account is not None and account.professor_id == profile_id
        assert account.professor_verification_status == ProfessorVerificationStatus.VERIFIED
        order = db.session.get(Order, order_id)
        assert order.professor_id == profile_id
        assert (order.professor_name, order.professor_faculty) == ("Maria Santos", "CCIS")
    sign_in(client, owner)
    assert b"Maria Santos" in client.get(placed.headers["Location"]).data


def test_delete_verified_account_removes_managed_profile_but_keeps_other_order_snapshot(client, test_app):
    blue, staff = blue_staff(test_app)
    profile_id = approved_professor(test_app, faculty="CCIS")
    with test_app.app_context():
        account_id = db.session.get(Professor, profile_id).account.id
    own_file = file(test_app, account_id, name="professor.pdf")
    with test_app.app_context():
        create_order(quote_order(user_id=account_id, file_id=own_file, shop_id=blue, max_quantity=999))
    owner = student(test_app)
    student_file = file(test_app, owner, name="student.pdf")
    sign_in(client, owner)
    assert professor_review(client, student_file, blue, profile_id).status_code == 200
    student_order = professor_place(client, student_file, blue, profile_id)
    assert student_order.status_code == 302
    sign_in(client, staff)
    path = f"/admin/professors/accounts/{account_id}/delete"
    assert path.encode() in client.get("/admin/professors").data
    page = client.get(path)
    assert b"private files, orders" in page.data
    assert client.post(path, data={"confirm_delete": "yes"}).status_code == 400
    deleted = confirm_delete(client, path)
    assert deleted.status_code == 302 and deleted.headers["Location"].endswith("/admin/professors")
    with test_app.app_context():
        assert db.session.get(User, account_id) is None
        assert db.session.get(UploadedFile, own_file) is None
        assert db.session.scalar(select(Order.id).where(Order.user_id == account_id)) is None
        assert db.session.get(Professor, profile_id) is None
        remaining = db.session.scalar(select(Order).where(Order.user_id == owner))
        assert remaining.professor_id is None
        assert (remaining.professor_name, remaining.professor_faculty) == ("Maria Santos", "CCIS")
    sign_in(client, owner)
    assert b"Maria Santos" in client.get(student_order.headers["Location"]).data


def test_delete_routes_are_blue_staff_only(client, test_app):
    blue, staff = blue_staff(test_app)
    profile_id = approved_professor(test_app)
    with test_app.app_context():
        account_id = db.session.get(Professor, profile_id).account.id
    profile_path = f"/admin/professors/{profile_id}/delete"
    account_path = f"/admin/professors/accounts/{account_id}/delete"
    other_shop = shop(test_app, name="CHALECOSPOT")
    other_staff = student(test_app, "other.staff@example.edu", UserRole.SHOP_STAFF)
    with test_app.app_context():
        db.session.get(User, other_staff).shop_id = other_shop
        db.session.commit()
    for actor in (student(test_app), student(test_app, "professor@example.edu", UserRole.PROFESSOR),
                  student(test_app, "admin@example.edu", UserRole.ADMIN), other_staff):
        sign_in(client, actor)
        for path in (profile_path, account_path):
            assert client.get(path).status_code == 403
            assert client.post(path, data={"csrf_token": token(client.get("/shop" if actor == other_staff else "/")),
                                           "confirm_delete": "yes"}).status_code == 403
    sign_in(client, staff)
    assert client.get("/admin/professors/999999/delete").status_code == 404
    assert client.get("/admin/professors/accounts/999999/delete").status_code == 404
    assert client.post(profile_path, data={"confirm_delete": "yes"}).status_code == 400
    with test_app.app_context():
        assert db.session.get(Professor, profile_id) is not None
