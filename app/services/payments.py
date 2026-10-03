"""Student payment intent and manual-reference submission."""

from __future__ import annotations

import re

from flask import current_app
from sqlalchemy import exists, select, update
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Order, OrderStatus, Payment, PaymentMethod, PaymentSettings, PaymentStatus
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


def payment_configuration() -> dict[str, str | bool]:
    """Admin-managed public values override the existing environment defaults."""
    saved = db.session.get(PaymentSettings, 1)
    if saved is not None:
        return {
            "online_enabled": saved.online_enabled,
            "online_instructions": saved.online_instructions,
            "online_account_name": saved.online_account_name,
            "online_destination": saved.online_destination,
            "onsite_instructions": saved.onsite_instructions,
        }
    config = current_app.config
    return {
        "online_enabled": config["ONLINE_PAYMENT_ENABLED"],
        "online_instructions": config["ONLINE_PAYMENT_INSTRUCTIONS"],
        "online_account_name": config["ONLINE_PAYMENT_ACCOUNT_NAME"],
        "online_destination": config["ONLINE_PAYMENT_DESTINATION"],
        "onsite_instructions": config["ONSITE_PAYMENT_INSTRUCTIONS"],
    }


def online_payment_details() -> dict[str, str] | None:
    """Only advertise online payment when every public instruction is configured."""
    config = payment_configuration()
    if not config["online_enabled"]:
        return None
    details = {
        "instructions": config["online_instructions"].strip(),
        "account_name": config["online_account_name"].strip(),
        "destination": config["online_destination"].strip(),
    }
    return details if all(details.values()) else None


def owned_order(order_reference: str, user_id: int) -> Order:
    order = db.session.scalar(select(Order).where(
        Order.order_reference == order_reference, Order.user_id == user_id,
    ))
    if order is None:
        raise PaymentError("Order not found.", 404)
    return order


def select_payment_method(*, order_reference: str, user_id: int, method: str) -> Payment:
    order = owned_order(order_reference, user_id)
    if order.status != OrderStatus.PENDING_PAYMENT:
        raise PaymentError("This order cannot accept payment selection.", 409)
    try:
        selected = PaymentMethod(method)
    except ValueError as error:
        raise PaymentError("Select a valid payment method.") from error
    if selected == PaymentMethod.ONLINE and online_payment_details() is None:
        raise PaymentError("Online payment is not configured for this service.")

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
    if online_payment_details() is None:
        raise PaymentError("Online payment is currently unavailable.", 409)
    cleaned = reference.strip() if isinstance(reference, str) else ""
    if not REFERENCE_PATTERN.fullmatch(cleaned):
        raise PaymentError("Enter a payment reference of 4–120 permitted characters.")
    if payment.payment_status == PaymentStatus.SUBMITTED and payment.payment_reference == cleaned:
        return payment  # Browser retry must not create another submission.
    if payment.payment_status != PaymentStatus.PENDING:
        raise PaymentError("Payment information was already submitted.", 409)
    result = db.session.execute(update(Payment).where(
        Payment.id == payment.id,
        Payment.payment_method == PaymentMethod.ONLINE,
        Payment.payment_status == PaymentStatus.PENDING,
        Payment.payment_reference.is_(None),
        Payment.amount == order.total, Payment.currency == order.currency,
        pending_order_for_payment(),
    ).values(
        payment_reference=cleaned, payment_status=PaymentStatus.SUBMITTED,
        updated_at=utc_now(),
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
