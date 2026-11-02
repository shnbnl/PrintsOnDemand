"""Customers can confirm receipt only for their own paid, ready orders."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import Order, OrderDestination, OrderStatus, Payment, PaymentMethod, PaymentStatus, UserRole
from test_orders import shop, sign_in, student, token


def order_for(app, owner, shop_id, *, reference, destination=OrderDestination.PICKUP,
              status=OrderStatus.READY, payment_status=PaymentStatus.PAID):
    with app.app_context():
        order = Order(
            user_id=owner, shop_id=shop_id, shop_name="Blue and Silver Bookstore",
            order_reference=reference, destination=destination, status=status,
            subtotal=Decimal("10.00"), fees_total=Decimal("0.00"),
            total=Decimal("10.00"), currency="PHP",
            ready_at=datetime(2026, 10, 9, tzinfo=timezone.utc),
        )
        db.session.add(order)
        db.session.flush()
        db.session.add(Payment(
            order_id=order.id, payment_method=PaymentMethod.ONSITE,
            payment_status=payment_status, amount=order.total, currency=order.currency,
        ))
        db.session.commit()


@pytest.mark.parametrize("role", [UserRole.STUDENT, UserRole.PROFESSOR])
def test_customer_completes_own_ready_order_from_history(client, test_app, role):
    owner = student(test_app, f"{role.value.lower()}-receipt@example.edu", role)
    shop_id = shop(test_app, name="Blue and Silver Bookstore")
    reference = f"POD-2026-{role.value}-RECEIPT"
    order_for(test_app, owner, shop_id, reference=reference)
    sign_in(client, owner)

    history = client.get("/orders")
    assert b"Complete order" in history.data
    detail = client.get(f"/orders/{reference}")
    assert b"Received your printed order?" in detail.data
    assert b"Next step:" in detail.data
    response = client.post(f"/orders/{reference}/complete", data={"csrf_token": token(history)})
    assert response.status_code == 302
    with test_app.app_context():
        order = db.session.scalar(select(Order).where(Order.order_reference == reference))
        assert order.status == OrderStatus.COMPLETED
        assert order.completed_at is not None
    assert b"Complete order" not in client.get("/orders").data
    completed_page = client.get(f"/orders/{reference}")
    assert b"Current order status" not in completed_page.data
    assert b"Next step:" not in completed_page.data
    assert b"Order completed" in completed_page.data
    assert b"This order is complete." in completed_page.data
    assert client.post(f"/orders/{reference}/complete", data={"csrf_token": token(client.get("/orders"))}).status_code == 409


def test_customer_completion_requires_owner_payment_and_handoff(client, test_app):
    owner = student(test_app)
    stranger = student(test_app, "other-receipt@example.edu")
    staff = student(test_app, "staff-receipt@example.edu", UserRole.SHOP_STAFF)
    shop_id = shop(test_app, name="Blue and Silver Bookstore")
    order_for(test_app, owner, shop_id, reference="POD-2026-UNPAID", payment_status=PaymentStatus.PENDING)
    order_for(test_app, owner, shop_id, reference="POD-2026-PRINTING", status=OrderStatus.PROCESSING)
    order_for(test_app, owner, shop_id, reference="POD-2026-UNDELIVERED",
              destination=OrderDestination.PROFESSOR)
    order_for(test_app, owner, shop_id, reference="POD-2026-RECEIVED",
              destination=OrderDestination.PROFESSOR, status=OrderStatus.DELIVERED)

    sign_in(client, owner)
    history = client.get("/orders")
    assert history.data.count(b"Complete order") == 1
    csrf = token(history)
    for reference in ("POD-2026-UNPAID", "POD-2026-PRINTING", "POD-2026-UNDELIVERED"):
        assert client.post(f"/orders/{reference}/complete", data={"csrf_token": csrf}).status_code == 409
    assert client.post("/orders/POD-2026-RECEIVED/complete").status_code == 400
    sign_in(client, stranger)
    assert client.post("/orders/POD-2026-RECEIVED/complete",
                       data={"csrf_token": token(client.get("/orders"))}).status_code == 404
    sign_in(client, staff)
    assert client.post("/orders/POD-2026-RECEIVED/complete",
                       data={"csrf_token": token(client.get("/shop"))}).status_code == 403
    sign_in(client, owner)
    assert client.post("/orders/POD-2026-RECEIVED/complete",
                       data={"csrf_token": token(client.get("/orders"))}).status_code == 302
