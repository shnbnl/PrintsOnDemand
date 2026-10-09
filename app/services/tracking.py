"""Read-only owner tracking derived from persisted order and payment state."""

from dataclasses import dataclass
from datetime import datetime

from app.models import Order, OrderDestination, OrderStatus, PaymentMethod, PaymentStatus


@dataclass(frozen=True)
class TrackingStep:
    title: str
    detail: str
    timestamp: datetime | None = None


@dataclass(frozen=True)
class OrderTracking:
    payment_method: str
    payment_status: str
    next_step: str
    steps: tuple[TrackingStep, ...]


def build_tracking(order: Order) -> OrderTracking:
    """Show only states supported by existing records; never create events."""
    payment = order.payment
    if payment is None:
        method = "Not selected"
        status = "Not started"
        payment_step = TrackingStep("Payment", "No payment method has been selected.")
        next_step = ("Choose online payment for professor delivery." if order.destination == OrderDestination.PROFESSOR
                     else "Choose online or onsite payment for this order.")
    elif payment.payment_status == PaymentStatus.PAID:
        method = payment.payment_method.value.title()
        status = PaymentStatus.PAID.value
        payment_step = TrackingStep(
            "Payment", ("Onsite cash confirmed by the shop." if payment.payment_method == PaymentMethod.ONSITE
                        else "Online payment manually verified.") if payment.reviewed_at else "Payment recorded as paid.",
            payment.reviewed_at or payment.updated_at,
        )
        next_step = {
            OrderStatus.PENDING_PAYMENT: "Wait for the printing shop to start processing.",
            OrderStatus.PROCESSING: "The printing shop is processing your order.",
            OrderStatus.READY: ("The printed papers are ready for physical delivery to the professor's Faculty."
                                if order.destination == OrderDestination.PROFESSOR else
                                "Your printed papers are ready. Confirm completion after receiving them."),
            OrderStatus.DELIVERED: "Blue and Silver staff recorded delivery to the professor's Faculty. Confirm completion after the handoff.",
            OrderStatus.COMPLETED: "This order is complete.",
        }[order.status]
    elif payment.payment_status == PaymentStatus.REJECTED:
        method = payment.payment_method.value.title()
        status = PaymentStatus.REJECTED.value
        payment_step = TrackingStep("Payment", "Submitted payment was rejected.", payment.reviewed_at)
        next_step = "Contact the printing shop about the rejected payment."
    elif payment.payment_method == PaymentMethod.ONSITE:
        method = "Onsite"
        status = payment.payment_status.value
        payment_step = TrackingStep(
            "Payment", "Onsite payment selected; payment is pending.", payment.updated_at
        )
        next_step = "Pay at the printing shop. Payment has not been recorded yet."
    else:
        method = "Online"
        status = payment.payment_status.value
        if payment.payment_status == PaymentStatus.SUBMITTED:
            payment_step = TrackingStep(
                "Payment", "Online payment reference submitted; awaiting manual verification.",
                payment.updated_at,
            )
            next_step = "Wait for manual payment verification. Shop processing has not started."
        elif payment.payment_status == PaymentStatus.PENDING:
            payment_step = TrackingStep(
                "Payment", "Online payment method selected; no reference submitted.",
                payment.updated_at,
            )
            next_step = "Follow the online instructions and submit your payment reference."

    order_detail = (
        f"{order.status.value}: awaiting payment or verification."
        if payment is None or payment.payment_status not in {PaymentStatus.PAID, PaymentStatus.REJECTED}
        else f"{order.status.value} is the recorded order status."
    )

    steps = [TrackingStep(
        "Order created", f"Order {order.order_reference} was created.", order.created_at
    ), payment_step]
    if order.destination == OrderDestination.PROFESSOR:
        fulfillment_detail = (
            f"Professor Delivery: {order.professor_name} at Faculty {order.professor_faculty or 'not recorded'} "
            "is the intended physical recipient. "
            + ("Staff recorded the physical handoff." if order.delivered_at else "No handoff confirmation is recorded.")
        )
    elif order.destination == OrderDestination.PICKUP:
        fulfillment_detail = f"Scheduled Pickup requested for {order.pickup_date}, {order.pickup_slot} Philippine time."
    elif order.destination == OrderDestination.DELIVERY:
        fulfillment_detail = (
            f"Delivery requested for {order.delivery_date}, {order.delivery_slot} Philippine time. "
            "No courier booking is recorded."
        )
    else:
        fulfillment_detail = None
    if fulfillment_detail:
        order_detail = f"{order_detail} {fulfillment_detail}"
    if order.processing_started_at:
        steps.append(TrackingStep("Processing started", "The shop began processing the print job.", order.processing_started_at))
    if order.ready_at:
        steps.append(TrackingStep("Order ready", "The shop finished the print job.", order.ready_at))
    if order.delivered_at:
        steps.append(TrackingStep("Delivered to Faculty", "Blue and Silver staff confirmed physical handoff of the printed papers.", order.delivered_at))
    if order.completed_at:
        steps.append(TrackingStep("Order completed", "This order was marked complete.", order.completed_at))
    steps.append(TrackingStep("Current order status", order_detail))

    return OrderTracking(
        payment_method=method,
        payment_status=status,
        next_step=next_step,
        steps=tuple(steps),
    )
