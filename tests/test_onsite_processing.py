"""Pay-onsite orders can print before cash, without marking the payment paid."""

from decimal import Decimal

import pytest
from sqlalchemy import select, text, update

from app.extensions import db
from app.models import Order, OrderStatus, Payment, PaymentMethod, PaymentStatus, User, UserRole
from app.services.order_processing import ProcessingError, advance_order, customer_can_complete
from test_customer_completion import order_for
from test_orders import file, place, review, shop, sign_in, student, token
from test_payments import choose
from test_shop_availability import staff_for
from test_staff_orders import action_post


@pytest.mark.parametrize("role", [UserRole.STUDENT, UserRole.PROFESSOR])
@pytest.mark.parametrize("shop_name", ["Blue and Silver Bookstore", "CHALECOSPOT", "Iced Design and Prints", "Pixels Print and Press"])
@pytest.mark.parametrize("cash_stage", ["PROCESSING", "READY"])
def test_onsite_orders_can_print_and_cash_can_be_collected_later(client, test_app, role, shop_name, cash_stage):
    owner = student(test_app, role=role)
    shop_id = shop(test_app, name=shop_name)
    staff = staff_for(test_app, shop_id, "cashier@example.edu")
    document = file(test_app, owner)
    sign_in(client, owner)
    assert review(client, document, shop_id).status_code == 200
    placed = place(client, document, shop_id)
    customer_url = placed.headers["Location"]
    assert choose(client, customer_url, "ONSITE").status_code == 302
    order = db.session.scalar(select(Order))
    payment_id = order.payment.id
    staff_url = customer_url.replace("/orders/", "/staff/orders/", 1)
    sign_in(client, staff)
    assert b'>Start processing<' in client.get(staff_url).data
    assert action_post(client, staff_url, "start_processing").status_code == 302
    if cash_stage == "READY":
        assert action_post(client, staff_url, "mark_ready").status_code == 302
    db.session.refresh(order)
    assert order.status.value == cash_stage
    before = (order.status, order.processing_started_at, order.ready_at, order.total)
    assert order.payment.payment_status == PaymentStatus.PENDING
    assert order.payment.reviewed_at is None
    assert not customer_can_complete(order)
    payment_url = f"/payments/verification/{payment_id}"
    assert payment_url.encode() in client.get("/payments/verification").data
    page = client.get(payment_url)
    assert b">Confirm cash received</button>" in page.data
    assert client.post(payment_url + "/confirm-onsite", data={
        "csrf_token": token(page), "cash_received": "yes",
    }).status_code == 302
    db.session.refresh(order)
    db.session.refresh(order.payment)
    assert (order.status, order.processing_started_at, order.ready_at, order.total) == before
    assert order.payment.payment_status == PaymentStatus.PAID
    assert order.payment.reviewed_by_id == staff
    assert payment_url.encode() not in client.get("/payments/verification").data


@pytest.mark.parametrize("invalid", ["amount", "currency", "reference", "REJECTED", "SUBMITTED"])
def test_invalid_onsite_payment_cannot_bypass_processing_guard(client, test_app, invalid):
    owner = student(test_app)
    shop_id = shop(test_app)
    staff = staff_for(test_app, shop_id, "cashier@example.edu")
    reference = "POD-2026-INVALID-CASH"
    order_for(test_app, owner, shop_id, reference=reference, status=OrderStatus.PENDING_PAYMENT,
              payment_status=PaymentStatus.PENDING)
    order = db.session.scalar(select(Order))
    payment = order.payment
    if invalid == "amount":
        payment.amount -= Decimal("0.01")
    elif invalid == "currency":
        payment.currency = "USD"
    elif invalid == "reference":
        payment.payment_reference = "FORGED-REFERENCE"
    else:
        if invalid == "SUBMITTED":
            payment.payment_method = PaymentMethod.ONLINE
            payment.payment_reference = "ONLINE-UNVERIFIED"
        payment.payment_status = PaymentStatus[invalid]
    db.session.commit()
    sign_in(client, staff)
    assert action_post(client, f"/staff/orders/{reference}", "start_processing").status_code == 409
    db.session.refresh(order)
    assert order.status == OrderStatus.PENDING_PAYMENT


def test_database_guard_rechecks_onsite_payment_after_a_stale_read(test_app):
    owner = student(test_app)
    shop_id = shop(test_app)
    staff = staff_for(test_app, shop_id, "cashier@example.edu")
    reference = "POD-2026-STALE-CASH"
    order_for(test_app, owner, shop_id, reference=reference, status=OrderStatus.PENDING_PAYMENT,
              payment_status=PaymentStatus.PENDING)
    order = db.session.scalar(select(Order))
    payment = order.payment
    actor = db.session.get(User, staff)
    db.session.connection().execute(update(Payment).where(Payment.id == payment.id).values(
        payment_status=PaymentStatus.REJECTED,
    ))
    assert payment.payment_status == PaymentStatus.PENDING  # Stale Python identity-map value.
    with pytest.raises(ProcessingError, match="order changed"):
        advance_order(actor, reference, "start_processing")
    assert db.session.execute(text("SELECT status FROM orders WHERE id=:id"), {"id": order.id}).scalar() == "PENDING_PAYMENT"
