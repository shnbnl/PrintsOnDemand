"""Manual review of submitted online references by authorized users."""

from __future__ import annotations

from sqlalchemy import exists, select, update
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import Order, OrderStatus, Payment, PaymentMethod, PaymentStatus, UserRole
from app.models.user import utc_now


class VerificationError(ValueError):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def review_scope(actor) -> int | None:
    if not getattr(actor, "is_authenticated", False):
        raise VerificationError("Sign in to review payments.", 403)
    if actor.role == UserRole.ADMIN:
        return None
    if actor.role != UserRole.SHOP_STAFF:
        raise VerificationError("Payment review access required.", 403)
    if actor.shop_id is None:
        raise VerificationError("No printing shop is assigned to this staff account.", 403)
    return actor.shop_id


def review_queue(actor) -> list[Payment]:
    shop_id = review_scope(actor)
    statement = (select(Payment).join(Order).where(
        Payment.payment_method == PaymentMethod.ONLINE,
        Payment.payment_status == PaymentStatus.SUBMITTED,
        Payment.payment_reference.is_not(None),
        Payment.amount == Order.total, Payment.currency == Order.currency,
        Order.status == OrderStatus.PENDING_PAYMENT,
    ).options(selectinload(Payment.order).selectinload(Order.user))
        .order_by(Payment.submitted_at.asc(), Payment.id.asc()))
    if shop_id is not None:
        statement = statement.where(Order.shop_id == shop_id)
    return db.session.scalars(statement).all()


def review_payment(actor, payment_id: int) -> Payment:
    shop_id = review_scope(actor)
    statement = (select(Payment).join(Order).where(
        Payment.id == payment_id, Payment.payment_method == PaymentMethod.ONLINE,
    ).options(selectinload(Payment.order).selectinload(Order.user),
              selectinload(Payment.reviewer)).execution_options(populate_existing=True))
    if shop_id is not None:
        statement = statement.where(Order.shop_id == shop_id)
    payment = db.session.scalar(statement)
    if payment is None:
        raise VerificationError("Payment not found.", 404)
    return payment


def decide_payment(actor, payment_id: int, *, reject: bool, reason: str = "") -> Payment:
    payment = review_payment(actor, payment_id)
    order = payment.order
    if payment.payment_status != PaymentStatus.SUBMITTED:
        raise VerificationError("This payment is no longer awaiting review. Reload the page.", 409)
    if (order.status != OrderStatus.PENDING_PAYMENT or not payment.payment_reference
            or payment.amount != order.total or payment.currency != order.currency):
        raise VerificationError("Payment details do not match a pending order.", 409)

    cleaned_reason = None
    if reject:
        if not isinstance(reason, str) or len(reason) > 500:
            raise VerificationError("Enter a rejection reason of at most 500 characters.", 400)
        cleaned_reason = " ".join(reason.split())
        if not cleaned_reason:
            raise VerificationError("Enter a rejection reason.", 400)
    now = utc_now()
    eligible_order = exists(select(Order.id).where(
        Order.id == Payment.order_id,
        Order.status == OrderStatus.PENDING_PAYMENT,
        Order.total == Payment.amount, Order.currency == Payment.currency,
        *((Order.shop_id == actor.shop_id,) if actor.role == UserRole.SHOP_STAFF else ()),
    ))
    result = db.session.execute(update(Payment).where(
        Payment.id == payment_id,
        Payment.payment_method == PaymentMethod.ONLINE,
        Payment.payment_status == PaymentStatus.SUBMITTED,
        Payment.payment_reference == payment.payment_reference,
        eligible_order,
    ).values(
        payment_status=PaymentStatus.REJECTED if reject else PaymentStatus.PAID,
        reviewed_at=now, reviewed_by_id=actor.id,
        rejection_reason=cleaned_reason, updated_at=now,
    ).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.session.rollback()
        raise VerificationError("This payment changed during review. Reload the page.", 409)
    db.session.commit()
    return db.session.get(Payment, payment_id, populate_existing=True)
