"""Stage 10 admin boundaries and historical-data protection."""

from decimal import Decimal

from sqlalchemy import select

from app.extensions import db
from app.models import (
    Order, Payment, PaymentSettings, PaymentStatus, PrintPrice, PrintingShop,
    Professor, ProfessorVerificationStatus, User, UserRole,
)
from test_orders import (
    file, offer_professor_service, place, professor_place, professor_review,
    review, shop, sign_in, student, token,
)
from test_payments import choose, submit
from test_staff_orders import setup_orders, staff_url


def post_with_token(client, path, data, *, token_page=None):
    if path.startswith("/admin/professors"):
        data = {"faculty": "MITL", "account_id": "0", **data}
    return client.post(path, data={
        "csrf_token": token(client.get(token_page or path)), **data,
    })


def test_dashboard_and_every_new_admin_route_are_role_guarded(client, test_app):
    admin = student(test_app, "admin@example.edu", UserRole.ADMIN)
    staff = student(test_app, "staff@example.edu", UserRole.SHOP_STAFF)
    learner = student(test_app)
    paths = (
        "/admin", "/admin/shops", "/admin/staff", "/admin/staff/1/assignment",
        "/admin/professors", "/admin/professors/new", "/admin/professors/1/edit",
        "/admin/payment",
    )
    for path in paths:
        assert client.get(path).status_code == 302
    for actor in (learner, staff):
        sign_in(client, actor)
        for path in paths:
            assert client.get(path).status_code == 403
        assert b"Admin management" not in client.get("/student" if actor == learner else "/shop").data
        assert client.post("/admin/payment", data={"csrf_token": token(client.get("/shop" if actor == staff else "/student"))}).status_code == 403
    sign_in(client, admin)
    dashboard = client.get("/admin")
    assert dashboard.status_code == 200
    for label in (b"Printing shops", b"Staff assignments", b"Payment configuration"):
        assert label in dashboard.data
    assert b"Admin management" in dashboard.data
    assert client.get("/admin/staff").status_code == 200
    assert client.get("/admin/professors").status_code == 403
    assert client.get("/admin/payment").status_code == 200
    assert b"password_hash" not in client.get("/admin/staff").data


def test_staff_reassignment_and_unassignment_change_access_immediately(client, test_app):
    owner, staff_a, _, url_a, url_b, item_a, _, _, _ = setup_orders(client, test_app)
    admin = student(test_app, "admin@example.edu", UserRole.ADMIN)
    with test_app.app_context():
        shop_a = db.session.scalar(select(Order).where(Order.order_reference == url_a.rsplit("/", 1)[1])).shop_id
        shop_b = db.session.scalar(select(Order).where(Order.order_reference == url_b.rsplit("/", 1)[1])).shop_id
    a, b = staff_url(url_a), staff_url(url_b)
    sign_in(client, staff_a)
    assert client.get(a).status_code == 200 and client.get(b).status_code == 404
    assert client.post(f"/admin/staff/{staff_a}/assignment", data={"shop_id": shop_b, "csrf_token": token(client.get(a))}).status_code == 403
    sign_in(client, admin)
    page = f"/admin/staff/{staff_a}/assignment"
    assert b"Blue and Silver Bookstore" in client.get("/admin/staff").data
    assert post_with_token(client, page, {"shop_id": str(shop_b), "role": "ADMIN"}).status_code == 302
    with test_app.app_context():
        user = db.session.get(User, staff_a)
        assert user.role == UserRole.SHOP_STAFF and user.shop_id == shop_b
    sign_in(client, staff_a)
    assert client.get(a).status_code == 404 and client.get(b).status_code == 200
    assert client.get(f"{a}/files/{item_a}/download").status_code == 404
    sign_in(client, admin)
    assert post_with_token(client, page, {"shop_id": "0"}).status_code == 302
    sign_in(client, staff_a)
    assert client.get("/staff/orders").status_code == 403
    assert client.get(a).status_code == 403 and client.get(b).status_code == 403
    sign_in(client, admin)
    assert post_with_token(client, page, {"shop_id": "999999"}).status_code == 200
    assert client.get(f"/admin/staff/{owner}/assignment").status_code == 404
    assert post_with_token(client, page, {"shop_id": str(shop_a)}).status_code == 302


def test_professor_management_eligibility_normalization_and_snapshots(client, test_app):
    admin = student(test_app, "blue@example.edu", UserRole.SHOP_STAFF)
    owner = student(test_app)
    shop_id = shop(test_app)
    file_id = file(test_app, owner)
    offer_professor_service(test_app, shop_id)
    account_id = student(test_app, "maria.santos@example.edu", UserRole.PROFESSOR)
    with test_app.app_context():
        db.session.get(User, admin).shop_id = shop_id
        db.session.get(User, account_id).name = "Maria Santos"
        db.session.get(User, account_id).professor_verification_status = ProfessorVerificationStatus.VERIFIED
        db.session.commit()
    sign_in(client, admin)
    path = "/admin/professors/new"
    assert client.post(path, data={"name": "No CSRF"}).status_code == 400
    created = post_with_token(client, path, {
        "name": "Maria Santos", "email": "  MARIA.SANTOS@EXAMPLE.EDU  ",
        "department": "Engineering", "office": "Room 204",
        "is_active": "y", "direct_send_approved": "y", "accepts_student_deliveries": "y", "role": "ADMIN",
        "account_id": str(account_id),
    })
    assert created.status_code == 302
    with test_app.app_context():
        professor = db.session.scalar(select(Professor))
        professor_id = professor.id
        assert professor.email == "maria.santos@example.edu"
    assert post_with_token(client, path, {"name": "Duplicate", "email": "MARIA.SANTOS@example.edu"}).status_code == 200
    with test_app.app_context():
        assert len(db.session.scalars(select(Professor)).all()) == 1
    sign_in(client, owner)
    assert b"Maria Santos" in client.get("/orders/new").data
    assert professor_review(client, file_id, shop_id, professor_id).status_code == 200
    old_url = professor_place(client, file_id, shop_id, professor_id).headers["Location"]
    sign_in(client, admin)
    edit = f"/admin/professors/{professor_id}/edit"
    assert post_with_token(client, edit, {
        "name": "Maria Updated", "email": "new.maria@example.edu",
        "department": "New Department", "office": "New Office", "account_id": str(account_id),
    }).status_code == 302
    with test_app.app_context():
        old = db.session.scalar(select(Order))
        assert old.professor_name == "Maria Santos"
        assert old.professor_email == "maria.santos@example.edu"
        assert not db.session.get(Professor, professor_id).is_active
    sign_in(client, owner)
    assert b"Maria Updated" not in client.get("/orders/new").data
    assert client.get(old_url).status_code == 200
    assert b"maria.santos@example.edu" in client.get(old_url).data
    sign_in(client, admin)
    assert post_with_token(client, edit, {
        "name": "Maria Updated", "email": "new.maria@example.edu",
        "department": "New Department", "office": "New Office",
        "is_active": "y", "direct_send_approved": "y", "accepts_student_deliveries": "y", "account_id": str(account_id),
    }).status_code == 302
    sign_in(client, owner)
    new_file = file(test_app, owner, name="new.pdf")
    assert b"Maria Updated" in client.get("/orders/new").data
    assert professor_review(client, new_file, shop_id, professor_id).status_code == 200
    new_url = professor_place(client, new_file, shop_id, professor_id).headers["Location"]
    with test_app.app_context():
        orders = db.session.scalars(select(Order).order_by(Order.id)).all()
        assert [order.professor_email for order in orders] == ["maria.santos@example.edu", "new.maria@example.edu"]
    assert b"new.maria@example.edu" in client.get(new_url).data
    sign_in(client, admin)
    assert post_with_token(client, edit, {
        "name": "Maria Updated", "email": "new.maria@example.edu", "is_active": "y", "account_id": str(account_id),
    }).status_code == 302
    sign_in(client, owner)
    assert b"Maria Updated" not in client.get("/orders/new").data


def test_payment_configuration_changes_student_flow_without_changing_records(client, test_app):
    admin = student(test_app, "admin@example.edu", UserRole.ADMIN)
    owner = student(test_app)
    shop_id = shop(test_app)
    file_id = file(test_app, owner)
    sign_in(client, owner)
    assert review(client, file_id, shop_id).status_code == 200
    order_url = place(client, file_id, shop_id).headers["Location"]
    assert b"Online payment" not in client.get(order_url).data
    sign_in(client, admin)
    path = "/admin/payment"
    assert client.get(path).status_code == 200
    assert post_with_token(client, path, {"online_enabled": "y"}).status_code == 405
    with test_app.app_context():
        assert db.session.get(PaymentSettings, 1) is None
        assert db.session.scalar(select(Payment)) is None
    sign_in(client, owner)
    assert b"Online payment" not in client.get(order_url).data
    assert choose(client, order_url, "ONLINE").status_code == 400
    with test_app.app_context():
        record = db.session.get(PrintingShop, shop_id)
        record.online_enabled = True
        record.online_account_name = "Campus Account"
        record.online_account_reference = "ACCOUNT-123"
        record.online_instructions = "Use this shop's transfer details."
        db.session.commit()
    assert choose(client, order_url, "ONLINE").status_code == 302
    assert b"Campus Account" in client.get(order_url).data


def test_admin_shop_changes_preserve_old_order_and_affect_new_quotes(client, test_app):
    admin = student(test_app, "admin@example.edu", UserRole.ADMIN)
    owner = student(test_app)
    shop_id = shop(test_app)
    file_id = file(test_app, owner)
    sign_in(client, owner)
    assert review(client, file_id, shop_id).status_code == 200
    old_url = place(client, file_id, shop_id).headers["Location"]
    sign_in(client, admin)
    edit = f"/admin/shops/{shop_id}/edit"
    assert post_with_token(client, f"/admin/shops/{shop_id}/prices", {
        "paper_size": "A4", "color_mode": "GRAYSCALE", "price": "3.00",
    }, token_page=edit).status_code == 302
    with test_app.app_context():
        old_order = db.session.scalar(select(Order))
        assert old_order.items[0].unit_price == Decimal("2.25")
        assert db.session.scalar(select(PrintPrice)).price == Decimal("3.00")
    sign_in(client, owner)
    new_file = file(test_app, owner, name="new.pdf")
    assert review(client, new_file, shop_id).status_code == 200
    new_url = place(client, new_file, shop_id).headers["Location"]
    with test_app.app_context():
        orders = db.session.scalars(select(Order).order_by(Order.id)).all()
        assert [order.items[0].unit_price for order in orders] == [Decimal("2.25"), Decimal("3.00")]
    sign_in(client, admin)
    assert post_with_token(client, edit, {
        "name": "Campus Prints", "address": "Campus Road",
        "opening_time": "09:00", "closing_time": "17:00",
    }).status_code == 302
    sign_in(client, owner)
    assert client.get(f"/shops/{shop_id}").status_code == 404
    assert client.get(old_url).status_code == 200
    with test_app.app_context():
        assert db.session.get(PrintingShop, shop_id).orders
    sign_in(client, admin)
    assert post_with_token(client, edit, {
        "name": "Campus Prints", "address": "Campus Road",
        "opening_time": "09:00", "closing_time": "17:00", "is_active": "y",
    }).status_code == 302
    sign_in(client, owner)
    assert client.get(f"/shops/{shop_id}").status_code == 200


def test_disabling_professor_service_blocks_new_use_but_keeps_old_order(client, test_app):
    admin = student(test_app, "admin@example.edu", UserRole.ADMIN)
    blue_staff = student(test_app, "blue@example.edu", UserRole.SHOP_STAFF)
    owner = student(test_app)
    shop_id = shop(test_app)
    file_id = file(test_app, owner)
    offer_professor_service(test_app, shop_id)
    account_id = student(test_app, "professor.one@example.edu", UserRole.PROFESSOR)
    with test_app.app_context():
        db.session.get(User, blue_staff).shop_id = shop_id
        db.session.get(User, account_id).name = "Professor One"
        db.session.get(User, account_id).professor_verification_status = ProfessorVerificationStatus.VERIFIED
        db.session.commit()
    sign_in(client, blue_staff)
    created = post_with_token(client, "/admin/professors/new", {
        "name": "Professor One", "email": "professor.one@example.edu",
        "is_active": "y", "direct_send_approved": "y", "accepts_student_deliveries": "y", "account_id": str(account_id),
    })
    assert created.status_code == 302
    with test_app.app_context():
        professor_id = db.session.scalar(select(Professor)).id
    sign_in(client, owner)
    assert professor_review(client, file_id, shop_id, professor_id).status_code == 200
    old_url = professor_place(client, file_id, shop_id, professor_id).headers["Location"]
    sign_in(client, admin)
    disabled = post_with_token(client, f"/admin/shops/{shop_id}/services", {
        "service_type": "DIRECT_TO_PROFESSOR",
    }, token_page=f"/admin/shops/{shop_id}/edit")
    assert disabled.status_code == 302
    sign_in(client, owner)
    fresh_file = file(test_app, owner, name="fresh.pdf")
    assert professor_review(client, fresh_file, shop_id, professor_id).status_code == 400
    assert b"Professor One" in client.get(old_url).data
    with test_app.app_context():
        assert db.session.scalar(select(Order)).professor_name == "Professor One"
