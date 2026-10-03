"""Authorized, shop-scoped manual review of online payment claims."""

from decimal import Decimal

import pytest
from flask import g
from sqlalchemy import select

from app.extensions import db
from app.models import Order, OrderStatus, Payment, PaymentStatus, User, UserRole
from app.services.order_processing import available_action
from test_orders import sign_in, student, token
from test_payments import choose, submit
from test_staff_orders import setup_orders


QUEUE = "/payments/verification"


def review_url(app, order_url):
    reference = order_url.rsplit("/", 1)[1]
    with app.app_context():
        payment = db.session.scalar(select(Payment).join(Order).where(Order.order_reference == reference))
        return f"{QUEUE}/{payment.id}"


def post_action(client, url, action, *, reason=None, **forged):
    data = {"csrf_token": token(client.get(url)), **forged}
    if reason is not None:
        data["reason"] = reason
    return client.post(f"{url}/{action}", data=data)


def test_admin_queue_verify_audit_and_processing_gate(client, test_app):
    owner, staff_a, staff_b, url_a, url_b, *_ = setup_orders(client, test_app)
    review_a = review_url(test_app, url_a)
    admin = student(test_app, "verify-admin@example.edu", role=UserRole.ADMIN)
    sign_in(client, admin)
    queue = client.get(QUEUE)
    assert queue.status_code == 200
    assert url_a.rsplit("/", 1)[1].encode() in queue.data
    assert url_b.rsplit("/", 1)[1].encode() not in queue.data
    for value in (b"Shop A", b"DEMO-REF-1234", b"ONLINE", b"SUBMITTED", b"PHP 6.75"):
        assert value in queue.data
    detail = client.get(review_a)
    assert detail.status_code == 200
    assert b"Verify payment as paid" in detail.data
    assert b"Maria Santos" not in detail.data  # No private file/professor details needed for review.
    assert client.get(review_a + "/verify").status_code == 405
    assert client.get(review_a + "/reject").status_code == 405
    assert client.post(review_a + "/verify", data={"payment_status": "PAID"}).status_code == 400

    with test_app.app_context():
        order = db.session.scalar(select(Order).where(Order.order_reference == url_a.rsplit("/", 1)[1]))
        assert available_action(order) is None
        before = (order.total, order.currency, order.items[0].line_total, order.payment.submitted_at)
    assert post_action(client, review_a, "verify", amount="0.01", currency="USD",
                       payment_status="REJECTED", shop_id="999", user_id="999").status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order).where(Order.order_reference == url_a.rsplit("/", 1)[1]))
        payment = order.payment
        assert payment.payment_status == PaymentStatus.PAID
        assert payment.reviewed_by_id == admin and payment.reviewed_at is not None
        assert payment.rejection_reason is None
        assert (order.total, order.currency, order.items[0].line_total, payment.submitted_at) == before
        assert order.status == OrderStatus.PENDING_PAYMENT
        assert order.processing_started_at is None
        assert available_action(order) == "start_processing"
    assert b"Verified by" in client.get(review_a).data
    assert review_a.encode() not in client.get(QUEUE).data
    assert post_action(client, review_a, "verify").status_code == 409
    assert post_action(client, review_a, "reject", reason="Too late").status_code == 409
    sign_in(client, owner)
    student_page = client.get(url_a)
    assert b"Payment verified" in student_page.data
    assert b"Payment status: PAID" in student_page.data
    assert b"Paid" in client.get("/orders").data


def test_admin_reject_reason_and_student_visibility(client, test_app):
    owner, _, _, url_a, _, *_ = setup_orders(client, test_app)
    review_a = review_url(test_app, url_a)
    admin = student(test_app, "reject-admin@example.edu", role=UserRole.ADMIN)
    sign_in(client, admin)
    assert post_action(client, review_a, "reject").status_code == 400
    assert post_action(client, review_a, "reject", reason="   \t ").status_code == 400
    assert post_action(client, review_a, "reject", reason="x" * 501).status_code == 400
    with test_app.app_context():
        assert db.session.scalar(select(Payment)).payment_status == PaymentStatus.SUBMITTED
    reason = "  Reference   did not match  <script>alert(1)</script>  "
    assert post_action(client, review_a, "reject", reason=reason,
                       amount="0.01", currency="USD", payment_status="PAID").status_code == 302
    with test_app.app_context():
        payment = db.session.scalar(select(Payment))
        assert payment.payment_status == PaymentStatus.REJECTED
        assert payment.rejection_reason == "Reference did not match <script>alert(1)</script>"
        assert payment.reviewed_by_id == admin and payment.reviewed_at is not None
        assert payment.order.status == OrderStatus.PENDING_PAYMENT
        assert available_action(payment.order) is None
    assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in client.get(review_a).data
    assert post_action(client, review_a, "reject", reason="Again").status_code == 409
    assert post_action(client, review_a, "verify").status_code == 409
    sign_in(client, owner)
    detail = client.get(url_a)
    assert b"Payment rejected" in detail.data
    assert b"Reason:</strong> Reference did not match" in detail.data
    assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in detail.data
    assert b"<script>alert(1)</script>" not in detail.data
    assert b"Payment rejected" in client.get("/orders").data


def test_student_unassigned_and_cross_shop_access_denied(client, test_app):
    owner, staff_a, staff_b, url_a, url_b, *_ = setup_orders(client, test_app)
    review_a = review_url(test_app, url_a)
    unassigned = student(test_app, "unassigned-verify@example.edu", role=UserRole.SHOP_STAFF)
    student_token = token(client.get(url_a))
    assert client.get(QUEUE).status_code == 403
    assert client.get(review_a).status_code == 403
    assert client.post(review_a + "/verify", data={"csrf_token": student_token}).status_code == 403
    assert client.post(review_a + "/reject", data={"csrf_token": student_token, "reason": "No"}).status_code == 403
    sign_in(client, unassigned)
    assert client.get(QUEUE).status_code == 403
    assert client.get(review_a).status_code == 403
    assert client.post(review_a + "/verify", data={"csrf_token": token(client.get("/shop"))}).status_code == 403
    sign_in(client, staff_b)
    assert client.get(review_a).status_code == 404
    assert url_a.rsplit("/", 1)[1].encode() not in client.get(QUEUE).data
    assert client.post(review_a + "/verify", data={"csrf_token": token(client.get(QUEUE))}).status_code == 404
    assert client.post(review_a + "/reject", data={"csrf_token": token(client.get(QUEUE)), "reason": "No"}).status_code == 404
    sign_in(client, staff_a)
    assert client.get(review_a).status_code == 200
    assert url_a.rsplit("/", 1)[1].encode() in client.get(QUEUE).data
    with test_app.app_context():
        assert db.session.scalar(select(Payment)).payment_status == PaymentStatus.SUBMITTED


def test_admin_sees_all_shops_staff_scope_and_reference_escaping(client, test_app):
    owner, staff_a, staff_b, url_a, url_b, *_ = setup_orders(client, test_app)
    sign_in(client, owner)
    assert choose(client, url_b, "ONLINE").status_code == 302
    assert submit(client, url_b, "SECOND-REF-123").status_code == 302
    review_a = review_url(test_app, url_a)
    review_b = review_url(test_app, url_b)
    with test_app.app_context():
        payment = db.session.get(Payment, int(review_b.rsplit("/", 1)[1]))
        payment.payment_reference = "<script>alert(1)</script>"
        db.session.commit()
    admin = student(test_app, "all-shops-admin@example.edu", role=UserRole.ADMIN)
    sign_in(client, admin)
    queue = client.get(QUEUE)
    assert review_a.encode() in queue.data and review_b.encode() in queue.data
    assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in queue.data
    assert b"<script>alert(1)</script>" not in queue.data
    detail = client.get(review_b)
    assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in detail.data
    sign_in(client, staff_a)
    queue = client.get(QUEUE)
    assert review_a.encode() in queue.data and review_b.encode() not in queue.data
    assert client.get(review_b).status_code == 404
    sign_in(client, staff_b)
    queue = client.get(QUEUE)
    assert review_a.encode() not in queue.data and review_b.encode() in queue.data


@pytest.mark.parametrize("action", ["verify", "reject"])
def test_assigned_staff_can_decide_only_assigned_submitted_payment(client, test_app, action):
    owner, staff_a, _, url_a, _, *_ = setup_orders(client, test_app)
    review_a = review_url(test_app, url_a)
    sign_in(client, staff_a)
    assert post_action(client, review_a, action, reason="  Invalid   reference  ").status_code == 302
    with test_app.app_context():
        payment = db.session.scalar(select(Payment))
        assert payment.payment_status == (PaymentStatus.PAID if action == "verify" else PaymentStatus.REJECTED)
        assert payment.reviewed_by_id == staff_a
        assert payment.rejection_reason == (None if action == "verify" else "Invalid reference")


@pytest.mark.parametrize("state,method", [
    (PaymentStatus.PENDING, "ONLINE"), (PaymentStatus.PENDING, "ONSITE"),
    (PaymentStatus.PAID, "ONLINE"), (PaymentStatus.REJECTED, "ONLINE"),
])
@pytest.mark.parametrize("action", ["verify", "reject"])
def test_ineligible_payment_cannot_be_reviewed(client, test_app, state, method, action):
    _, _, _, url_a, _, *_ = setup_orders(client, test_app)
    review_a = review_url(test_app, url_a)
    admin = student(test_app, "state-admin@example.edu", role=UserRole.ADMIN)
    with test_app.app_context():
        payment = db.session.scalar(select(Payment))
        payment.payment_status = state
        if state == PaymentStatus.PENDING:
            payment.payment_reference = None
        if method == "ONSITE":
            payment.payment_method = "ONSITE"
        db.session.commit()
    sign_in(client, admin)
    assert review_a.encode() not in client.get(QUEUE).data
    if method == "ONLINE":
        assert post_action(client, review_a, action, reason="No payment found").status_code == 409
    else:
        assert client.get(review_a).status_code == 404
        assert client.post(review_a + "/" + action, data={
            "csrf_token": token(client.get(QUEUE)), "reason": "No payment found",
        }).status_code == 404
    with test_app.app_context():
        assert db.session.scalar(select(Payment)).payment_status == state


@pytest.mark.parametrize("first,second,expected", [
    ("verify", "reject", PaymentStatus.PAID),
    ("reject", "verify", PaymentStatus.REJECTED),
])
def test_stale_second_review_cannot_overwrite_first(client, test_app, first, second, expected):
    _, staff_a, _, url_a, _, *_ = setup_orders(client, test_app)
    review_a = review_url(test_app, url_a)
    admin = student(test_app, "race-admin@example.edu", role=UserRole.ADMIN)
    sign_in(client, admin)
    stale_client = test_app.test_client()
    sign_in(stale_client, staff_a)
    g.pop("csrf_token", None)
    stale_page = stale_client.get(review_a)
    assert stale_page.status_code == 200
    stale_token = token(stale_page)
    g.pop("_login_user", None)
    g.pop("csrf_token", None)
    assert post_action(client, review_a, first, reason="First reviewer decision").status_code == 302
    g.pop("_login_user", None)
    response = stale_client.post(review_a + "/" + second, data={
        "csrf_token": stale_token, "reason": "Second reviewer decision",
    })
    assert response.status_code == 409, response.data[:800]
    assert b"no longer awaiting review" in response.data
    with test_app.app_context():
        payment = db.session.scalar(select(Payment))
        assert payment.payment_status == expected
        assert payment.reviewed_by_id == admin


def test_submitted_payment_still_blocks_processing_until_verified(client, test_app):
    _, staff_a, _, url_a, _, *_ = setup_orders(client, test_app)
    review_a = review_url(test_app, url_a)
    admin = student(test_app, "gate-admin@example.edu", role=UserRole.ADMIN)
    staff_order = url_a.replace("/orders/", "/staff/orders/", 1)
    sign_in(client, staff_a)
    assert client.post(staff_order + "/advance", data={
        "csrf_token": token(client.get(staff_order)), "action": "start_processing",
    }).status_code == 409
    sign_in(client, admin)
    assert post_action(client, review_a, "verify").status_code == 302
    sign_in(client, staff_a)
    assert client.post(staff_order + "/advance", data={
        "csrf_token": token(client.get(staff_order)), "action": "start_processing",
    }).status_code == 302
    with test_app.app_context():
        assert db.session.scalar(select(Payment)).amount == Decimal("6.75")


def test_rejected_payment_cannot_start_processing(client, test_app):
    _, staff_a, _, url_a, _, *_ = setup_orders(client, test_app)
    review_a = review_url(test_app, url_a)
    admin = student(test_app, "gate-reject-admin@example.edu", role=UserRole.ADMIN)
    sign_in(client, admin)
    assert post_action(client, review_a, "reject", reason="No matching transfer").status_code == 302
    staff_order = url_a.replace("/orders/", "/staff/orders/", 1)
    sign_in(client, staff_a)
    assert client.post(staff_order + "/advance", data={
        "csrf_token": token(client.get(staff_order)), "action": "start_processing",
    }).status_code == 409
    with test_app.app_context():
        order = db.session.scalar(select(Order).where(Order.order_reference == url_a.rsplit("/", 1)[1]))
        assert order.status == OrderStatus.PENDING_PAYMENT
