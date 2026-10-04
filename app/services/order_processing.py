"""Shop-scoped, payment-gated order processing."""

from dataclasses import dataclass

from sqlalchemy import exists, select, update

from app.extensions import db
from app.models import Order, OrderDestination, OrderStatus, Payment, PaymentStatus, UserRole
from app.models.user import utc_now
from app.services.professors import PROFESSOR_DELIVERY_SHOP


@dataclass(frozen=True)
class ProcessingError(Exception):
    message: str
    status_code: int


# A requested action must match the persisted state. Replaying an old form cannot
# silently advance an order a second time.
TRANSITIONS = {
    "start_processing": (OrderStatus.PENDING_PAYMENT, OrderStatus.PROCESSING, "processing_started_at"),
    "mark_ready": (OrderStatus.PROCESSING, OrderStatus.READY, "ready_at"),
    "mark_delivered": (OrderStatus.READY, OrderStatus.DELIVERED, "delivered_at"),
    "complete_professor": (OrderStatus.DELIVERED, OrderStatus.COMPLETED, "completed_at"),
    "complete": (OrderStatus.READY, OrderStatus.COMPLETED, "completed_at"),
}
NEXT_ACTION = {current: action for action, (current, _, _) in TRANSITIONS.items()}


def assigned_shop_id(actor) -> int:
    if not getattr(actor, "is_authenticated", False) or actor.role != UserRole.SHOP_STAFF:
        raise ProcessingError("Staff access required.", 403)
    if actor.shop_id is None:
        raise ProcessingError("No printing shop is assigned to this staff account.", 403)
    return actor.shop_id


def list_staff_orders(actor) -> list[Order]:
    shop_id = assigned_shop_id(actor)
    return db.session.scalars(
        select(Order).where(Order.shop_id == shop_id)
        .order_by(Order.created_at.desc(), Order.id.desc())
    ).all()


def get_staff_order(actor, order_reference: str) -> Order:
    shop_id = assigned_shop_id(actor)
    order = db.session.scalar(select(Order).where(
        Order.shop_id == shop_id, Order.order_reference == order_reference,
    ))
    if order is None:
        raise ProcessingError("Order not found.", 404)
    return order


def available_action(order: Order) -> str | None:
    if (
        order.payment is None
        or order.payment.payment_status != PaymentStatus.PAID
        or order.payment.amount != order.total
        or order.payment.currency != order.currency
    ):
        return None
    if order.destination == OrderDestination.PROFESSOR and order.shop.name == PROFESSOR_DELIVERY_SHOP:
        return {
            OrderStatus.READY: "mark_delivered",
            OrderStatus.DELIVERED: "complete_professor",
        }.get(order.status, NEXT_ACTION.get(order.status))
    return NEXT_ACTION.get(order.status) if order.status != OrderStatus.DELIVERED else None


def advance_order(actor, order_reference: str, action: str) -> Order:
    order = get_staff_order(actor, order_reference)
    transition = TRANSITIONS.get(action)
    if transition is None or order.status != transition[0]:
        raise ProcessingError("This processing action is not available for the order's current state.", 409)
    if available_action(order) != action:
        raise ProcessingError("Payment must be recorded as paid for this order's total before processing.", 409)
    if action == "mark_delivered" and (
        order.destination != OrderDestination.PROFESSOR or actor.shop.name != PROFESSOR_DELIVERY_SHOP
    ):
        raise ProcessingError("Only Blue and Silver staff can confirm professor delivery.", 403)

    now = utc_now()
    paid_payment = exists(select(Payment.id).where(
        Payment.order_id == Order.id, Payment.payment_status == PaymentStatus.PAID,
        Payment.amount == Order.total, Payment.currency == Order.currency,
    ))
    result = db.session.execute(
        update(Order).where(
            Order.id == order.id, Order.shop_id == actor.shop_id,
            Order.status == transition[0], paid_payment,
        ).values(status=transition[1], updated_at=now, **{transition[2]: now})
    )
    if result.rowcount != 1:
        db.session.rollback()
        raise ProcessingError("The order changed. Reload it before trying again.", 409)
    db.session.commit()
    return get_staff_order(actor, order_reference)
