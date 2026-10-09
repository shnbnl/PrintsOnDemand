"""Shop-isolated staff processing and truthful student tracking."""

from datetime import datetime, timezone
from decimal import Decimal

from flask import g
import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import Order, OrderStatus, Payment, PaymentStatus, Professor, UploadedFile, User
from app.services.order_processing import ProcessingError, advance_order, available_action, get_staff_order
from app.services.tracking import build_tracking
from test_orders import (
    PDF, approved_professor, file, offer_professor_service, place, professor_place,
    professor_review, review, shop, sign_in, student, token,
)
from test_payments import choose, configured_online, submit


def setup_orders(client, app):
    configured_online(app)
    owner = student(app)
    shop_a = shop(app, name="Blue and Silver Bookstore")
    shop_b = shop(app, name="Shop B")
    staff_a = student(app, "staff-a@example.edu", role="SHOP_STAFF")
    staff_b = student(app, "staff-b@example.edu", role="SHOP_STAFF")
    with app.app_context():
        db.session.get(User, staff_a).shop_id = shop_a
        db.session.get(User, staff_b).shop_id = shop_b
        db.session.commit()
    file_a = file(app, owner, name="lecture.pdf")
    file_b = file(app, owner, name="other.pdf")
    unattached = file(app, owner, name="unattached.pdf")
    offer_professor_service(app, shop_a)
    professor = approved_professor(app)
    sign_in(client, owner)
    assert professor_review(client, file_a, shop_a, professor).status_code == 200
    url_a = professor_place(client, file_a, shop_a, professor).headers["Location"]
    assert review(client, file_b, shop_b).status_code == 200
    url_b = place(client, file_b, shop_b).headers["Location"]
    assert choose(client, url_a, "ONLINE").status_code == 302
    assert submit(client, url_a, "DEMO-REF-1234").status_code == 302
    with app.app_context():
        item_a = db.session.scalar(select(Order).where(Order.shop_id == shop_a)).items[0].id
        item_b = db.session.scalar(select(Order).where(Order.shop_id == shop_b)).items[0].id
        key = db.session.get(UploadedFile, file_a).storage_key
    return owner, staff_a, staff_b, url_a, url_b, item_a, item_b, unattached, key


def staff_url(student_url):
    return student_url.replace("/orders/", "/staff/orders/", 1)


def action_post(client, url, action, **extras):
    return client.post(url + "/advance", data={
        "csrf_token": token(client.get(url)), "action": action, **extras,
    })


def test_staff_list_detail_and_shop_isolation(client, test_app):
    owner, staff_a, staff_b, url_a, url_b, item_a, item_b, unattached, key = setup_orders(client, test_app)
    other_student = student(test_app, "another-student@example.edu")
    other_file = file(test_app, other_student, name="another-student.pdf")
    admin = student(test_app, "admin@example.edu", role="ADMIN")
    a = staff_url(url_a)
    b = staff_url(url_b)
    assert client.get("/staff/orders").status_code == 403  # signed in as student
    g.pop("_login_user", None)
    assert test_app.test_client().get("/staff/orders").status_code == 302
    sign_in(client, staff_a)
    listing = client.get("/staff/orders")
    assert listing.status_code == 200
    assert a.rsplit("/", 1)[1].encode() in listing.data
    assert b.rsplit("/", 1)[1].encode() not in listing.data
    assert b"SUBMITTED" in listing.data and b"PENDING_PAYMENT" in listing.data
    detail = client.get(a)
    assert detail.status_code == 200
    for expected in (b"lecture.pdf", b"A4", b"Grayscale", b"PHP 6.75", b"DEMO-REF-1234", b"Maria Santos", b"Computer Engineering", b"Engineering Building 204"):
        assert expected in detail.data
    assert key.encode() not in detail.data
    assert b"instance/uploads" not in detail.data
    assert client.get(b).status_code == 404
    assert client.post(b + "/advance", data={"csrf_token": token(detail), "action": "start_processing"}).status_code == 404
    assert client.get(f"{b}/files/{item_b}/download").status_code == 404
    assert client.get(f"{a}/files/{item_b}/download").status_code == 404
    assert client.get(f"{a}/files/{unattached}/download").status_code == 404
    assert client.get(f"{a}/files/{other_file}/download").status_code == 404
    downloaded = client.get(f"{a}/files/{item_a}/download")
    assert downloaded.status_code == 200 and downloaded.data == PDF
    assert downloaded.headers["Content-Disposition"].startswith("attachment;")
    sign_in(client, staff_b)
    assert client.get(a).status_code == 404
    assert client.get(b).status_code == 200
    sign_in(client, owner)
    assert client.get(a).status_code == 403
    assert client.get(f"{a}/files/{item_a}/download").status_code == 403
    assert client.get(f"/files/{item_a}/download").status_code == 200  # owner route unchanged
    sign_in(client, admin)
    assert client.get("/staff/orders").status_code == 403
    assert client.get(a).status_code == 403


def test_staff_dashboard_counts_only_assigned_shop_work(client, test_app):
    _, staff_a, staff_b, url_a, url_b, *_ = setup_orders(client, test_app)
    reference_a = url_a.rsplit("/", 1)[1]
    reference_b = url_b.rsplit("/", 1)[1]
    sign_in(client, staff_a)
    dashboard = client.get("/shop")
    assert dashboard.status_code == 200
    assert reference_a.encode() in dashboard.data
    assert reference_b.encode() not in dashboard.data
    assert b"<strong>1</strong><span>Payment actions</span>" in dashboard.data
    assert b"<strong>0</strong><span>Ready to print</span>" in dashboard.data
    with test_app.app_context():
        order = db.session.scalar(select(Order).where(Order.order_reference == reference_a))
        order.payment.payment_status = PaymentStatus.PAID
        db.session.commit()
    # The test fixture keeps an app context open across requests; expire its
    # identity map so the next request sees the committed payment update.
    db.session.expire_all()
    dashboard = client.get("/shop")
    assert b"<strong>0</strong><span>Payment actions</span>" in dashboard.data
    assert b"<strong>1</strong><span>Ready to print</span>" in dashboard.data
    sign_in(client, staff_b)
    dashboard = client.get("/shop")
    assert reference_b.encode() in dashboard.data
    assert reference_a.encode() not in dashboard.data


def test_unverified_payment_blocks_processing_and_form_forgery(client, test_app):
    owner, staff_a, _, url_a, _, _, _, _, _ = setup_orders(client, test_app)
    a = staff_url(url_a)
    sign_in(client, staff_a)
    detail = client.get(a)
    assert b"Processing is unavailable until payment is recorded as paid" in detail.data
    assert action_post(client, a, "start_processing", payment_status="PAID", status="COMPLETED").status_code == 409
    assert action_post(client, a, "complete").status_code == 409
    assert client.post(a + "/advance", data={"action": "start_processing"}).status_code == 400
    assert client.get(a + "/advance").status_code == 405
    with test_app.app_context():
        order = db.session.scalar(select(Order).where(Order.order_reference == url_a.rsplit("/", 1)[1]))
        assert order.status == OrderStatus.PENDING_PAYMENT
        assert order.processing_started_at is None
        assert order.payment.payment_status == PaymentStatus.SUBMITTED
        assert order.payment.amount == Decimal("6.75")
        assert build_tracking(order).steps[-2].timestamp == order.payment.updated_at


@pytest.mark.parametrize("mismatch", ["amount", "currency"])
def test_paid_payment_must_match_order_total_and_currency(client, test_app, mismatch):
    _, staff_id, _, student_url, _, _, _, _, _ = setup_orders(client, test_app)
    staff_order_url = staff_url(student_url)
    reference = student_url.rsplit("/", 1)[1]
    with test_app.app_context():
        order = db.session.scalar(select(Order).where(Order.order_reference == reference))
        order.payment.payment_status = PaymentStatus.PAID
        if mismatch == "amount":
            order.payment.amount = order.total - Decimal("0.01")
        else:
            order.payment.currency = "USD"
        db.session.commit()

    sign_in(client, staff_id)
    detail = client.get(staff_order_url)
    assert detail.status_code == 200
    assert b"Processing is unavailable" in detail.data
    assert action_post(client, staff_order_url, "start_processing").status_code == 409
    with test_app.app_context():
        order = db.session.scalar(select(Order).where(Order.order_reference == reference))
        assert order.status == OrderStatus.PENDING_PAYMENT
        assert order.processing_started_at is None
        order.payment.amount = order.total
        order.payment.currency = order.currency
        db.session.commit()
        assert order.payment.payment_status == PaymentStatus.PAID
        assert available_action(order) == "start_processing"
    # The test fixture keeps an application context open across requests.
    db.session.expire_all()
    assert action_post(client, staff_order_url, "start_processing").status_code == 302


def test_paid_record_allows_only_sequential_processing_and_tracking(client, test_app, monkeypatch):
    owner, staff_a, _, url_a, _, _, _, _, _ = setup_orders(client, test_app)
    a = staff_url(url_a)
    from app.services import order_processing
    times = iter([
        datetime(2026, 10, 3, 1, tzinfo=timezone.utc),
        datetime(2026, 10, 3, 2, tzinfo=timezone.utc),
        datetime(2026, 10, 3, 3, tzinfo=timezone.utc),
        datetime(2026, 10, 3, 4, tzinfo=timezone.utc),
    ])
    monkeypatch.setattr(order_processing, "utc_now", lambda: next(times))
    with test_app.app_context():
        order = db.session.scalar(select(Order).where(Order.order_reference == url_a.rsplit("/", 1)[1]))
        original = (order.user_id, order.shop_id, order.total, order.professor_name, order.items[0].unit_price)
        db.session.get(Professor, order.professor_id).name = "Changed Later"
        # Trusted fixture represents a future authorized verifier; no HTTP route can set PAID.
        order.payment.payment_status = PaymentStatus.PAID
        db.session.commit()
    sign_in(client, staff_a)
    assert action_post(client, a, "complete").status_code == 409
    assert action_post(client, a, "start_processing", completed_at="1999-01-01", total="0.01", professor_name="Forged", payment_status="PAID").status_code == 302
    assert action_post(client, a, "start_processing").status_code == 409
    assert action_post(client, a, "complete").status_code == 409
    assert action_post(client, a, "mark_ready").status_code == 302
    assert action_post(client, a, "complete").status_code == 409
    assert action_post(client, a, "mark_delivered").status_code == 302
    assert action_post(client, a, "complete_professor").status_code == 409
    assert action_post(client, a, "complete").status_code == 409
    sign_in(client, owner)
    tracking = client.get(url_a)
    assert b"Complete order" in tracking.data
    assert client.post(url_a + "/complete", data={"csrf_token": token(tracking)}).status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order).where(Order.order_reference == url_a.rsplit("/", 1)[1]))
        assert order.status == OrderStatus.COMPLETED
        assert (order.processing_started_at.hour, order.ready_at.hour, order.delivered_at.hour, order.completed_at.hour) == (1, 2, 3, 4)
        assert (order.user_id, order.shop_id, order.total, order.professor_name, order.items[0].unit_price) == original
        assert order.payment.payment_status == PaymentStatus.PAID
        steps = build_tracking(order).steps
        assert [step.title for step in steps] == ["Order created", "Payment", "Processing started", "Order ready", "Delivered to Faculty", "Order completed", "Current order status"]
        assert [step.timestamp.hour for step in steps[2:6]] == [1, 2, 3, 4]
    tracking = client.get(url_a)
    assert tracking.status_code == 200
    assert b"Processing started" in tracking.data and b"Order ready" in tracking.data and b"Order completed" in tracking.data
    assert b"Maria Santos" in tracking.data and b"Changed Later" not in tracking.data
    assert b"No shop processing has been confirmed" not in tracking.data


def test_service_rechecks_role_assignment_and_order_scope(client, test_app):
    owner, staff_a, _, url_a, url_b, _, _, _, _ = setup_orders(client, test_app)
    with test_app.app_context():
        student_actor = db.session.get(User, owner)
        staff_actor = db.session.get(User, staff_a)
        for actor, ref, expected in (
            (student_actor, url_a.rsplit("/", 1)[1], 403),
            (staff_actor, url_b.rsplit("/", 1)[1], 404),
        ):
            try:
                get_staff_order(actor, ref)
                assert False
            except ProcessingError as error:
                assert error.status_code == expected
        staff_actor.shop_id = None
        db.session.flush()
        try:
            advance_order(staff_actor, url_a.rsplit("/", 1)[1], "start_processing")
            assert False
        except ProcessingError as error:
            assert error.status_code == 403
