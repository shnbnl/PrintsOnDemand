"""Student payment intent and manual-reference submission."""

from __future__ import annotations

import re

from sqlalchemy import exists, select, update
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Order, OrderDestination, OrderStatus, Payment, PaymentMethod, PaymentStatus, PrintingShop, UserRole
from app.models.user import utc_now


REFERENCE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._/-]{3,119}\Z")


def pending_order_for_payment():
    return exists(select(Order.id).where(
        Order.id == Payment.order_id, Order.status == OrderStatus.PENDING_PAYMENT,
    ))


class PaymentError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def online_payment_details(shop: PrintingShop) -> dict[str, str] | None:
    """Show only this shop's enabled online payment configuration."""
    db.session.refresh(shop, attribute_names=[
        "cash_enabled", "online_enabled", "payment_qr_digest", "online_instructions",
        "online_account_name", "online_account_reference",
    ])
    if not shop.online_enabled or not shop.payment_qr_digest:
        return None
    return {
        "instructions": shop.online_instructions.strip(),
        "account_name": shop.online_account_name.strip(),
        "destination": shop.online_account_reference.strip(),
    }


def owned_order(order_reference: str, user_id: int) -> Order:
    order = db.session.scalar(select(Order).where(
        Order.order_reference == order_reference, Order.user_id == user_id,
    ))
    if order is None:
        raise PaymentError("Order not found.", 404)
    db.session.refresh(order.shop, attribute_names=["cash_enabled"])
    return order


def normalize_payment_reference(reference: str) -> str:
    if isinstance(reference, str) and len(reference) > 120:
        raise PaymentError("Payment reference number is too long.")
    cleaned = " ".join(reference.split()) if isinstance(reference, str) else ""
    if not cleaned:
        raise PaymentError("Enter your payment reference number.")
    if not REFERENCE_PATTERN.fullmatch(cleaned):
        raise PaymentError("Please enter a valid payment reference number.")
    return cleaned


def validate_checkout_payment(*, shop: PrintingShop, destination: OrderDestination, method: str,
                              actor_role: UserRole | None = None,
                              reference: str = "") -> tuple[PaymentMethod, str | None]:
    """Validate pre-order payment intent without treating it as paid."""
    try:
        selected = PaymentMethod(method)
    except ValueError as error:
        raise PaymentError("Select a valid payment method.") from error
    if destination == OrderDestination.PROFESSOR and selected != PaymentMethod.ONLINE and actor_role != UserRole.PROFESSOR:
        raise PaymentError("Student professor delivery requires online payment.")
    if selected == PaymentMethod.ONLINE and online_payment_details(shop) is None:
        raise PaymentError("Online payment is unavailable for this shop.")
    if selected == PaymentMethod.ONSITE and not shop.cash_enabled:
        raise PaymentError("Onsite cash payment is unavailable for this shop.")
    if selected == PaymentMethod.ONSITE and reference.strip():
        raise PaymentError("A payment reference is only accepted for online payment.")
    if selected == PaymentMethod.ONLINE:
        if not reference:
            raise PaymentError("Payment reference number is required for online payment.")
        return selected, normalize_payment_reference(reference)
    return selected, None


def select_payment_method(*, order_reference: str, user_id: int, method: str) -> Payment:
    order = owned_order(order_reference, user_id)
    if order.status != OrderStatus.PENDING_PAYMENT:
        raise PaymentError("This order cannot accept payment selection.", 409)
    try:
        selected = PaymentMethod(method)
    except ValueError as error:
        raise PaymentError("Select a valid payment method.") from error
    if order.destination == OrderDestination.PROFESSOR and selected != PaymentMethod.ONLINE and order.user.role != UserRole.PROFESSOR:
        raise PaymentError("Student professor delivery requires online payment.")
    if selected == PaymentMethod.ONLINE and online_payment_details(order.shop) is None:
        raise PaymentError("Online payment is unavailable for this shop.")
    if selected == PaymentMethod.ONSITE and not order.shop.cash_enabled:
        raise PaymentError("Onsite cash payment is unavailable for this shop.")

    payment = order.payment
    if payment is not None:
        if payment.amount != order.total or payment.currency != order.currency:
            raise PaymentError("Payment amount no longer matches the order.", 409)
        if payment.payment_method == selected:
            return payment  # Repeated selection is harmless, including after submission.
        if payment.payment_status != PaymentStatus.PENDING:
            raise PaymentError("A submitted payment method cannot be changed.", 409)
        result = db.session.execute(update(Payment).where(
            Payment.id == payment.id,
            Payment.payment_status == PaymentStatus.PENDING,
            Payment.amount == order.total, Payment.currency == order.currency,
            pending_order_for_payment(),
        ).values(
            payment_method=selected, payment_reference=None, updated_at=utc_now(),
        ).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            db.session.rollback()
            raise PaymentError("Payment selection changed. Reload this order.", 409)
        db.session.commit()
        return db.session.get(Payment, payment.id, populate_existing=True)
    else:
        payment = Payment(
            order_id=order.id, payment_method=selected,
            payment_status=PaymentStatus.PENDING,
            amount=order.total, currency=order.currency,
        )
        db.session.add(payment)
    try:
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        # The unique order constraint also guards concurrent first selections.
        existing = owned_order(order_reference, user_id).payment
        if existing is not None and existing.payment_method == selected:
            return existing
        raise PaymentError("Payment selection changed. Reload this order.", 409) from error
    return payment


def submit_online_reference(*, order_reference: str, user_id: int, reference: str) -> Payment:
    order = owned_order(order_reference, user_id)
    payment = order.payment
    if payment is None or payment.payment_method != PaymentMethod.ONLINE:
        raise PaymentError("Select online payment first.", 409)
    if order.status != OrderStatus.PENDING_PAYMENT:
        raise PaymentError("This order cannot accept payment information.", 409)
    if payment.amount != order.total or payment.currency != order.currency:
        raise PaymentError("Payment amount no longer matches the order.", 409)
    if online_payment_details(order.shop) is None:
        raise PaymentError("Online payment is currently unavailable.", 409)
    cleaned = normalize_payment_reference(reference)
    if payment.payment_status == PaymentStatus.SUBMITTED and payment.payment_reference == cleaned:
        return payment  # Browser retry must not create another submission.
    if payment.payment_status != PaymentStatus.PENDING:
        raise PaymentError("Payment information was already submitted.", 409)
    now = utc_now()
    result = db.session.execute(update(Payment).where(
        Payment.id == payment.id,
        Payment.payment_method == PaymentMethod.ONLINE,
        Payment.payment_status == PaymentStatus.PENDING,
        Payment.payment_reference.is_(None),
        Payment.amount == order.total, Payment.currency == order.currency,
        pending_order_for_payment(),
    ).values(
        payment_reference=cleaned, payment_status=PaymentStatus.SUBMITTED,
        submitted_at=now, updated_at=now,
    ).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.session.rollback()
        current = db.session.get(Payment, payment.id, populate_existing=True)
        if (current is not None and current.payment_status == PaymentStatus.SUBMITTED
                and current.payment_reference == cleaned):
            return current
        raise PaymentError("Payment information was already submitted.", 409)
    db.session.commit()
    return db.session.get(Payment, payment.id, populate_existing=True)
