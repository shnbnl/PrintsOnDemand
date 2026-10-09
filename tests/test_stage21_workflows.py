"""Stage 21 account, Faculty, payment, and physical-handoff boundaries."""

from sqlalchemy import select

from app.extensions import db
from app.models import Order, OrderStatus, Payment, PaymentStatus, Professor, ProfessorVerificationStatus, User, UserRole
from app.services.payments import PaymentError, select_payment_method
from app.services.orders import create_order
from app.services.pricing import quote_order
from test_auth import PASSWORD, login, register
from test_orders import (approved_professor, file, offer_professor_service, professor_place,
                         professor_review, shop, sign_in, student, token)
from test_payments import configured_online
from test_staff_orders import action_post, staff_url


def test_public_role_selection_and_invalid_role_rejection(client, test_app):
    page = client.get("/auth/register")
    assert b"Account Type" in page.data and b"Student" in page.data and b"Professor" in page.data
    assert register(client, account_type="STUDENT").status_code == 302
    assert register(client, account_type="PROFESSOR", name="Professor Name",
                    email="professor@example.edu", professor_department="CCIS").status_code == 302
    invalid = register(client, account_type="SHOP_STAFF", email="forged@example.edu")
    assert invalid.status_code == 200
    with test_app.app_context():
        users = db.session.scalars(select(User).order_by(User.id)).all()
        assert [user.role for user in users] == [UserRole.STUDENT, UserRole.PROFESSOR]
        assert users[1].professor_id is None
    assert login(client, email="professor@example.edu").headers["Location"].endswith("/professor")
    assert client.get("/professor").status_code == 200
    assert client.get("/admin/professors").status_code == 403
    pending = client.get("/account")
    assert pending.status_code == 200 and b"Verification" in pending.data


def test_four_staff_accounts_are_provisioned_outside_public_registration(test_app):
    names = ("Blue and Silver Bookstore", "CHALECOSPOT", "Iced Design and Prints", "Pixels Print and Press")
    ids = [shop(test_app, name=name) for name in names]
    runner = test_app.test_cli_runner()
    for index, shop_id in enumerate(ids):
        result = runner.invoke(args=[
            "create-privileged-user", "--role", "SHOP_STAFF", "--shop-id", str(shop_id),
            "--name", f"Shop Staff {index}", "--email", f"staff{index}@example.edu",
        ], input=f"{PASSWORD}\n{PASSWORD}\n")
        assert result.exit_code == 0, result.output
    with test_app.app_context():
        users = db.session.scalars(select(User).where(User.role == UserRole.SHOP_STAFF).order_by(User.id)).all()
        assert [user.shop_id for user in users] == ids


def test_blue_staff_verifies_and_manages_professor_approvals(client, test_app):
    blue = shop(test_app, name="Blue and Silver Bookstore")
    others = [shop(test_app, name=name) for name in (
        "CHALECOSPOT", "Iced Design and Prints", "Pixels Print and Press"
    )]
    blue_staff = student(test_app, "blue@example.edu", role=UserRole.SHOP_STAFF)
    other_staff = [student(test_app, f"other{index}@example.edu", role=UserRole.SHOP_STAFF)
                   for index in range(3)]
    with test_app.app_context():
        db.session.get(User, blue_staff).shop_id = blue
        for user_id, shop_id in zip(other_staff, others):
            db.session.get(User, user_id).shop_id = shop_id
        db.session.commit()
    assert register(client, account_type="PROFESSOR", name="Juan Dela Cruz",
                    email="juan@example.edu", professor_department="CCIS").status_code == 302
    with test_app.app_context():
        professor_account = db.session.scalar(select(User).where(User.email == "juan@example.edu"))
        account_id = professor_account.id
    for actor in [student(test_app), *other_staff, account_id]:
        sign_in(client, actor)
        assert client.get("/admin/professors").status_code == 403
        assert client.get("/admin/professors/new").status_code == 403
        assert client.post("/admin/professors/new", data={"csrf_token": token(client.get("/shop" if actor in other_staff else "/student" if actor != account_id else "/professor"))}).status_code == 403
    sign_in(client, blue_staff)
    pending = client.get("/admin/professors")
    assert b"Juan Dela Cruz" in pending.data
    assert client.post(f"/admin/professors/accounts/{account_id}/verify", data={
        "csrf_token": token(pending),
    }).status_code == 302
    assert client.get("/admin/professors/new").status_code == 404
    with test_app.app_context():
        profile = db.session.get(User, account_id).professor
        assert (profile.department, profile.faculty, profile.account.id, profile.accepts_student_deliveries) == (
            "CCIS", "Information Technology", account_id, False,
        )
        profile_id = profile.id
    edit = f"/admin/professors/{profile_id}/edit"
    assert client.post(edit, data={
        "csrf_token": token(client.get(edit)), "name": "Juan Dela Cruz", "email": "juan@example.edu",
        "faculty": "NOT_A_FACULTY", "account_id": str(account_id), "is_active": "y",
        "direct_send_approved": "y", "accepts_student_deliveries": "y",
    }).status_code == 302
    with test_app.app_context():
        assert db.session.get(Professor, profile_id).faculty == "Information Technology"
    assert client.post(edit, data={
        "csrf_token": token(client.get(edit)), "name": "Juan Dela Cruz", "email": "juan@example.edu",
        "faculty": "MITL", "account_id": str(account_id), "is_active": "y",
        "direct_send_approved": "y",
    }).status_code == 302
    with test_app.app_context():
        profile = db.session.get(Professor, profile_id)
        assert profile.faculty == "Information Technology" and not profile.accepts_student_deliveries


def test_student_faculty_snapshot_online_payment_and_staff_handoff(client, test_app):
    configured_online(test_app)
    blue = shop(test_app, name="Blue and Silver Bookstore")
    other = shop(test_app, name="CHALECOSPOT")
    offer_professor_service(test_app, blue)
    offer_professor_service(test_app, other)
    professor_id = approved_professor(test_app, faculty="CCIS")
    student_id = student(test_app)
    staff_id = student(test_app, "staff@example.edu", role=UserRole.SHOP_STAFF)
    with test_app.app_context():
        db.session.get(User, staff_id).shop_id = blue
        db.session.commit()
    file_id = file(test_app, student_id)
    sign_in(client, student_id)
    assert professor_review(client, file_id, other, professor_id).status_code == 400
    assert client.get("/orders/new", query_string={
        "file_id": file_id, "shop_id": blue, "destination": "PROFESSOR",
        "professor_id": professor_id, "professor_faculty": "GE",
    }).status_code == 400
    review = professor_review(client, file_id, blue, professor_id)
    assert review.status_code == 200 and b"CCIS" in review.data
    order_url = professor_place(client, file_id, blue, professor_id).headers["Location"]
    detail = client.get(order_url)
    assert b"Faculty: CCIS" in detail.data
    assert b"Delivery location: Einstein Building 3rd Floor" in detail.data
    assert b'value="ONSITE"' not in detail.data
    assert b"Change intended professor" not in detail.data
    assert client.post(order_url + "/professor", data={
        "csrf_token": token(detail), "professor_id": str(professor_id),
    }).status_code == 400
    assert client.post(order_url + "/payment", data={
        "csrf_token": token(detail), "payment_method": "ONSITE",
    }).status_code == 400
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert (order.professor_id, order.professor_faculty) == (professor_id, "CCIS")
        assert db.session.scalar(select(Payment)) is None
        try:
            select_payment_method(order_reference=order.order_reference, user_id=student_id, method="ONSITE")
        except PaymentError:
            pass
        else:
            assert False, "service accepted onsite payment"
        db.session.get(Professor, professor_id).faculty = "MITL"
        db.session.commit()
    assert b"Faculty: CCIS" in client.get(order_url).data
    assert b"CCIS" in client.get("/orders").data
    assert client.post(order_url + "/payment", data={
        "csrf_token": token(client.get(order_url)), "payment_method": "ONLINE",
    }).status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        order.payment.payment_status = PaymentStatus.PAID
        db.session.commit()
    staff_path = staff_url(order_url)
    assert client.post(staff_path + "/advance", data={
        "csrf_token": token(client.get(order_url)), "action": "mark_delivered",
    }).status_code == 403
    sign_in(client, staff_id)
    staff_detail = client.get(staff_path)
    assert b"Faculty" in staff_detail.data and b"CCIS" in staff_detail.data
    assert action_post(client, staff_path, "mark_delivered").status_code == 409
    assert action_post(client, staff_path, "start_processing").status_code == 302
    assert action_post(client, staff_path, "mark_ready").status_code == 302
    assert action_post(client, staff_path, "complete").status_code == 409
    assert action_post(client, staff_path, "mark_delivered").status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert order.status == OrderStatus.DELIVERED and order.delivered_at is not None
    sign_in(client, student_id)
    assert b"Delivered to Faculty" in client.get(order_url).data


def test_legacy_onsite_order_cannot_be_converted_to_professor_delivery(client, test_app):
    blue = shop(test_app, name="Blue and Silver Bookstore")
    offer_professor_service(test_app, blue)
    professor_id = approved_professor(test_app)
    student_id = student(test_app)
    file_id = file(test_app, student_id)
    with test_app.app_context():
        order = create_order(quote_order(
            user_id=student_id, file_id=file_id, shop_id=blue, max_quantity=999,
        ))
        reference = order.order_reference
        select_payment_method(order_reference=reference, user_id=student_id, method="ONSITE")
    sign_in(client, student_id)
    detail = client.get(f"/orders/{reference}")
    assert b"Change intended professor" not in detail.data
    assert client.post(f"/orders/{reference}/professor", data={
        "csrf_token": token(detail), "professor_id": str(professor_id),
    }).status_code == 400
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert order.destination is None and order.professor_id is None


def test_professor_self_uses_managed_faculty_even_with_acceptance_off(client, test_app):
    blue = shop(test_app, name="Blue and Silver Bookstore")
    offer_professor_service(test_app, blue)
    profile_id = approved_professor(test_app, accepts=False, faculty="MITL", linked=False)
    account_id = student(test_app, "maria.santos@example.edu", role=UserRole.PROFESSOR)
    with test_app.app_context():
        db.session.get(User, account_id).professor_id = profile_id
        db.session.get(User, account_id).professor_verification_status = ProfessorVerificationStatus.VERIFIED
        db.session.commit()
    file_id = file(test_app, account_id)
    sign_in(client, account_id)
    page = client.get("/orders/new", query_string={"shop_id": blue})
    assert b"Deliver to Faculty" in page.data and b'id="professor_id"' not in page.data
    assert b'id="professor_faculty"' not in page.data
    invalid = client.get("/orders/new", query_string={
        "file_id": file_id, "shop_id": blue, "destination": "PROFESSOR", "professor_faculty": "INVALID",
    })
    assert invalid.status_code == 400
    assert client.get("/orders/new", query_string={
        "file_id": file_id, "shop_id": blue, "destination": "PROFESSOR", "professor_faculty": "GE",
    }).status_code == 400
    reviewed = client.get("/orders/new", query_string={
        "file_id": file_id, "shop_id": blue, "destination": "PROFESSOR",
    })
    assert reviewed.status_code == 200 and b"MITL" in reviewed.data
    placed = client.post("/orders/create", data={
        "csrf_token": token(reviewed), "file_id": file_id, "shop_id": blue,
        "destination": "PROFESSOR",
    })
    assert placed.status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order))
        assert (order.professor_recipient_type, order.professor_faculty) == ("SELF", "MITL")
        assert db.session.get(Professor, profile_id).accepts_student_deliveries is False
