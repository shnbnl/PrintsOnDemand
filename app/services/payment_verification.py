"""Shop-scoped review of online claims and confirmation of onsite cash."""

from __future__ import annotations

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import Order, OrderDestination, OrderStatus, Payment, PaymentMethod, PaymentStatus, PrintingShop, User, UserRole
from app.models.user import utc_now
from app.services.professors import PROFESSOR_DELIVERY_SHOP


class VerificationError(ValueError):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


ONSITE_COLLECTION_STATES = (
    OrderStatus.PENDING_PAYMENT, OrderStatus.PROCESSING, OrderStatus.READY, OrderStatus.DELIVERED,
)


def onsite_cash_order_query():
    return and_(
        Order.status.in_(ONSITE_COLLECTION_STATES),
        or_(Order.destination.is_(None), Order.destination != OrderDestination.PROFESSOR,
            faculty_cash_handoff_query()),
    )


def can_collect_onsite_cash(payment: Payment) -> bool:
    order = payment.order
    return bool(
        payment.payment_method == PaymentMethod.ONSITE
        and payment.payment_status == PaymentStatus.PENDING
        and payment.payment_reference is None
        and payment.amount == order.total and payment.currency == order.currency
        and order.status in ONSITE_COLLECTION_STATES
        and (order.destination != OrderDestination.PROFESSOR or (
            order.professor_recipient_type == "SELF" and order.user.role == UserRole.PROFESSOR
            and order.shop.name == PROFESSOR_DELIVERY_SHOP
        ))
    )


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
        or_(
            and_(Payment.payment_method == PaymentMethod.ONLINE,
                 Payment.payment_status == PaymentStatus.SUBMITTED,
                 Payment.payment_reference.is_not(None),
                 Order.status == OrderStatus.PENDING_PAYMENT),
            and_(Payment.payment_method == PaymentMethod.ONSITE,
                 Payment.payment_status == PaymentStatus.PENDING,
                 Payment.payment_reference.is_(None),
                 onsite_cash_order_query()),
        ),
        Payment.amount == Order.total, Payment.currency == Order.currency,
    ).options(selectinload(Payment.order).selectinload(Order.user))
        .order_by(Payment.created_at.asc(), Payment.id.asc()))
    if shop_id is not None:
        statement = statement.where(Order.shop_id == shop_id)
    return db.session.scalars(statement).all()


def faculty_cash_handoff_query():
    return and_(
        Order.destination == OrderDestination.PROFESSOR,
        Order.professor_recipient_type == "SELF",
        Order.status.in_((OrderStatus.PENDING_PAYMENT, OrderStatus.PROCESSING,
                          OrderStatus.READY, OrderStatus.DELIVERED)),
        Order.shop_id.in_(select(PrintingShop.id).where(PrintingShop.name == PROFESSOR_DELIVERY_SHOP)),
        Order.user_id.in_(select(User.id).where(User.role == UserRole.PROFESSOR)),
    )


def review_payment(actor, payment_id: int) -> Payment:
    shop_id = review_scope(actor)
    statement = (select(Payment).join(Order).where(
        Payment.id == payment_id,
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
    if payment.payment_method != PaymentMethod.ONLINE:
        raise VerificationError("Online review is unavailable for this payment.", 409)
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
    if not reject:
        # Keep verification and the start of printing in the same transaction.
        # A stale order must roll back the payment decision as well.
        started = db.session.execute(update(Order).where(
            Order.id == order.id, Order.status == OrderStatus.PENDING_PAYMENT,
            Order.total == payment.amount, Order.currency == payment.currency,
            *((Order.shop_id == actor.shop_id,) if actor.role == UserRole.SHOP_STAFF else ()),
        ).values(status=OrderStatus.PROCESSING, processing_started_at=now, updated_at=now)
            .execution_options(synchronize_session=False))
        if started.rowcount != 1:
            db.session.rollback()
            raise VerificationError("The order changed during review. Reload the page.", 409)
    db.session.commit()
    return db.session.get(Payment, payment_id, populate_existing=True)


def confirm_onsite_cash(actor, payment_id: int) -> Payment:
    """Record collected cash; start printing if the order has not begun yet."""
    payment = review_payment(actor, payment_id)
    order = payment.order
    if payment.payment_method != PaymentMethod.ONSITE or payment.payment_status != PaymentStatus.PENDING:
        raise VerificationError("This onsite payment is no longer awaiting cash. Reload the page.", 409)
    if not can_collect_onsite_cash(payment):
        raise VerificationError("Payment details do not match an order awaiting onsite cash.", 409)

    now = utc_now()
    eligible_order = exists(select(Order.id).where(
        Order.id == Payment.order_id,
        onsite_cash_order_query(),
        Order.total == Payment.amount, Order.currency == Payment.currency,
        *((Order.shop_id == actor.shop_id,) if actor.role == UserRole.SHOP_STAFF else ()),
    ))
    recorded = db.session.execute(update(Payment).where(
        Payment.id == payment_id,
        Payment.payment_method == PaymentMethod.ONSITE,
        Payment.payment_status == PaymentStatus.PENDING,
        Payment.payment_reference.is_(None),
        eligible_order,
    ).values(payment_status=PaymentStatus.PAID, reviewed_at=now,
             reviewed_by_id=actor.id, updated_at=now)
        .execution_options(synchronize_session=False))
    if recorded.rowcount != 1:
        db.session.rollback()
        raise VerificationError("This payment changed during review. Reload the page.", 409)
    if order.status == OrderStatus.PENDING_PAYMENT:
        started = db.session.execute(update(Order).where(
            Order.id == order.id, Order.status == OrderStatus.PENDING_PAYMENT,
            Order.total == payment.amount, Order.currency == payment.currency,
            *((Order.shop_id == actor.shop_id,) if actor.role == UserRole.SHOP_STAFF else ()),
        ).values(status=OrderStatus.PROCESSING, processing_started_at=now, updated_at=now)
            .execution_options(synchronize_session=False))
        if started.rowcount != 1:
            db.session.rollback()
            raise VerificationError("The order changed during review. Reload the page.", 409)
    db.session.commit()
    return db.session.get(Payment, payment_id, populate_existing=True)
