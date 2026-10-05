"""Authorized, shop-scoped manual review of online payment claims."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from flask import g
from sqlalchemy import select

from app.extensions import db
from app.models import Order, OrderStatus, Payment, PaymentMethod, PaymentStatus, User, UserRole
from app.services.order_processing import available_action
from test_orders import file, place, review, shop, sign_in, student, token
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
    for value in (b"Blue and Silver Bookstore", b"DEMO-REF-1234", b"ONLINE", b"SUBMITTED", b"PHP 6.75"):
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
        assert order.status == OrderStatus.PROCESSING
        assert order.processing_started_at == payment.reviewed_at
        assert available_action(order) == "mark_ready"
        other_order = db.session.scalar(select(Order).where(Order.order_reference == url_b.rsplit("/", 1)[1]))
        assert other_order.status == OrderStatus.PENDING_PAYMENT
        assert other_order.processing_started_at is None
    assert b"Verified by" in client.get(review_a).data
    assert review_a.encode() not in client.get(QUEUE).data
    assert post_action(client, review_a, "verify").status_code == 409
    assert post_action(client, review_a, "reject", reason="Too late").status_code == 409
    sign_in(client, owner)
    student_page = client.get(url_a)
    assert b"Payment verified" in student_page.data
    assert b"Payment verified" in student_page.data
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
    (PaymentStatus.PENDING, "ONLINE"),
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
    assert post_action(client, review_a, action, reason="No payment found").status_code == 409
    with test_app.app_context():
        assert db.session.scalar(select(Payment)).payment_status == state
        assert db.session.scalar(select(Payment)).order.status == OrderStatus.PENDING_PAYMENT
        assert db.session.scalar(select(Payment)).order.processing_started_at is None


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
    }).status_code == 409
    with test_app.app_context():
        assert db.session.scalar(select(Payment)).amount == Decimal("6.75")
        assert db.session.scalar(select(Payment)).order.status == OrderStatus.PROCESSING


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


@pytest.mark.parametrize("shop_name", [
    "Blue and Silver Bookstore", "CHALECOSPOT", "Iced Design and Prints", "Pixels Print and Press",
])
def test_each_shop_staff_can_confirm_collected_onsite_cash(client, test_app, shop_name):
    owner = student(test_app, f"cash-owner-{shop_name.replace(' ', '')}@example.edu")
    shop_id = shop(test_app, name=shop_name)
    staff = student(test_app, f"cash-staff-{shop_id}@example.edu", role=UserRole.SHOP_STAFF)
    with test_app.app_context():
        db.session.get(User, staff).shop_id = shop_id
        db.session.commit()
    uploaded = file(test_app, owner)
    sign_in(client, owner)
    assert review(client, uploaded, shop_id).status_code == 200
    order_url = place(client, uploaded, shop_id).headers["Location"]
    assert choose(client, order_url, "ONSITE").status_code == 302
    payment_url = review_url(test_app, order_url)
    with test_app.app_context():
        order = db.session.scalar(select(Order).where(Order.order_reference == order_url.rsplit("/", 1)[1]))
        before = (order.total, order.currency, order.items[0].line_total)
    sign_in(client, staff)
    dashboard = client.get("/shop")
    assert b"<strong>1</strong><span>Payment actions</span>" in dashboard.data
    assert b"Confirm onsite cash" in dashboard.data
    queue = client.get(QUEUE)
    assert payment_url.encode() in queue.data
    assert shop_name.encode() in queue.data
    assert b"Confirm onsite cash" in queue.data
    detail = client.get(payment_url)
    assert b"Confirm cash received and start printing" in detail.data
    assert b"Payment reference</dt>" not in detail.data
    assert b"Confirm onsite cash after collection" in client.get(
        order_url.replace("/orders/", "/staff/orders/", 1)
    ).data
    assert client.post(payment_url + "/confirm-onsite").status_code == 400  # CSRF
    assert post_action(client, payment_url, "confirm-onsite").status_code == 400  # no cash received
    assert post_action(client, payment_url, "verify").status_code == 409  # online action is separate
    assert post_action(client, payment_url, "reject", reason="No transfer").status_code == 409
    assert post_action(client, payment_url, "confirm-onsite", cash_received="yes",
                       amount="0.01", currency="USD", shop_id="999").status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order).where(Order.order_reference == order_url.rsplit("/", 1)[1]))
        assert (order.total, order.currency, order.items[0].line_total) == before
        assert order.payment.payment_method == PaymentMethod.ONSITE
        assert order.payment.payment_status == PaymentStatus.PAID
        assert order.payment.reviewed_by_id == staff
        assert order.payment.reviewed_at == order.processing_started_at
        assert order.status == OrderStatus.PROCESSING
    assert payment_url.encode() not in client.get(QUEUE).data
    assert b"Cash confirmed by" in client.get(payment_url).data
    assert post_action(client, payment_url, "confirm-onsite", cash_received="yes").status_code == 409
    sign_in(client, owner)
    assert b"shop confirmed receipt" in client.get(order_url).data


def test_onsite_cash_confirmation_is_shop_scoped(client, test_app):
    owner, staff_a, staff_b, _, url_b, *_ = setup_orders(client, test_app)
    sign_in(client, owner)
    assert choose(client, url_b, "ONSITE").status_code == 302
    payment_url = review_url(test_app, url_b)
    assert client.get(payment_url).status_code == 403
    sign_in(client, staff_a)
    assert payment_url.encode() not in client.get(QUEUE).data
    assert client.get(payment_url).status_code == 404
    assert client.post(payment_url + "/confirm-onsite", data={
        "csrf_token": token(client.get(QUEUE)), "cash_received": "yes",
    }).status_code == 404
    sign_in(client, staff_b)
    assert payment_url.encode() in client.get(QUEUE).data
    assert post_action(client, payment_url, "confirm-onsite", cash_received="yes").status_code == 302


def test_onsite_confirmation_rolls_back_if_printing_cannot_start(client, test_app, monkeypatch):
    owner, _, _, _, url_b, *_ = setup_orders(client, test_app)
    sign_in(client, owner)
    assert choose(client, url_b, "ONSITE").status_code == 302
    payment_url = review_url(test_app, url_b)
    admin = student(test_app, "onsite-admin@example.edu", role=UserRole.ADMIN)
    sign_in(client, admin)
    execute = db.session.execute

    def conflict(statement, *args, **kwargs):
        if getattr(statement, "is_update", False) and statement.table.name == "orders":
            return SimpleNamespace(rowcount=0)
        return execute(statement, *args, **kwargs)

    monkeypatch.setattr(db.session, "execute", conflict)
    assert post_action(client, payment_url, "confirm-onsite", cash_received="yes").status_code == 409
    with test_app.app_context():
        payment = db.session.scalar(select(Payment).where(Payment.id == int(payment_url.rsplit("/", 1)[1])))
        assert payment.payment_status == PaymentStatus.PENDING
        assert payment.reviewed_at is None and payment.reviewed_by_id is None
        assert payment.order.status == OrderStatus.PENDING_PAYMENT
        assert payment.order.processing_started_at is None
