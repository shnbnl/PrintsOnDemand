"""Read-only student tracking derived from persisted order and payment state."""

from dataclasses import dataclass
from datetime import datetime

from app.models import Order, PaymentMethod, PaymentStatus


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
    steps: tuple[TrackingStep, TrackingStep, TrackingStep]


def build_tracking(order: Order) -> OrderTracking:
    """Show only states supported by existing records; never create events."""
    payment = order.payment
    if payment is None:
        method = "Not selected"
        status = "Not started"
        payment_step = TrackingStep("Payment", "No payment method has been selected.")
        next_step = "Choose online or onsite payment for this order."
    elif payment.payment_status == PaymentStatus.PAID:
        method = payment.payment_method.value.title()
        status = PaymentStatus.PAID.value
        payment_step = TrackingStep("Payment", "Payment recorded as paid.")
        next_step = "Payment was recorded. Shop processing is not tracked in this stage."
    elif payment.payment_status == PaymentStatus.REJECTED:
        method = payment.payment_method.value.title()
        status = PaymentStatus.REJECTED.value
        payment_step = TrackingStep("Payment", "Submitted payment was rejected.")
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

    return OrderTracking(
        payment_method=method,
        payment_status=status,
        next_step=next_step,
        steps=(
            TrackingStep(
                "Order created", f"Order {order.order_reference} was created.", order.created_at
            ),
            payment_step,
            TrackingStep(
                "Current order status", order_detail
            ),
        ),
    )
