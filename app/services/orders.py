"""Atomic order creation from a fresh server-side quote."""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Order, OrderDestination, OrderItem, OrderStatus, Payment, PaymentStatus, Professor, User
from app.models.user import utc_now
from app.services.pricing import CartQuote, OrderQuote
from app.services.professors import assign_professor, validate_professor_selection
from app.services.fulfillment import Fulfillment, FulfillmentError, validate_fulfillment
from app.services.payments import validate_checkout_payment
from app.services.pricing import PricingError, verify_quote_page_counts


def create_order(
    quote: CartQuote | OrderQuote, *, destination: str | None = None,
    professor_id: str | int | None = None,
    fulfillment: Fulfillment | None = None,
    payment_method: str | None = None,
    payment_reference: str = "",
) -> Order:
    """Commit one order and all quoted items, retrying rare reference collisions."""
    try:
        verify_quote_page_counts(quote)
    except PricingError as error:
        raise FulfillmentError(str(error)) from error
    for _ in range(5):
        actor = db.session.get(User, quote.user_id)
        if actor is None:
            raise FulfillmentError("Order account no longer exists.")
        if fulfillment is not None:
            refreshed = validate_fulfillment(shop=quote.shop, values=fulfillment.fields(), actor=actor)
            if refreshed.snapshot() != fulfillment.snapshot() or refreshed.delivery_fee != getattr(quote, "delivery_fee", 0):
                raise FulfillmentError("Fulfillment details or delivery fee changed. Review the order again.")
            professor = db.session.get(Professor, refreshed.professor_id) if refreshed.professor_id else None
        else:
            professor = validate_professor_selection(
                shop_id=quote.shop.id, destination=destination, professor_id=professor_id, actor=actor
            )
        payment_choice = None
        if payment_method is not None:
            if fulfillment is None:
                raise FulfillmentError("Choose fulfillment before payment.")
            payment_choice = validate_checkout_payment(
                shop=quote.shop, destination=fulfillment.destination, method=payment_method,
                reference=payment_reference,
            )
        reference = f"POD-{utc_now().year}-{secrets.token_hex(6).upper()}"
        order = Order(
            user_id=quote.user_id,
            shop_id=quote.shop.id,
            order_reference=reference,
            shop_name=quote.shop.name,
            status=OrderStatus.PENDING_PAYMENT,
            subtotal=quote.subtotal,
            rush_fee=quote.rush_fee,
            delivery_fee=getattr(quote, "delivery_fee", 0),
            fees_total=quote.fees_total,
            total=quote.total,
            currency=quote.currency,
        )
        if professor is not None:
            assign_professor(order, professor, faculty=(fulfillment.professor_details or {}).get("faculty") if fulfillment else None)
            order.professor_recipient_type = (fulfillment.professor_recipient_type if fulfillment
                                              else "STUDENT_SELECTED")
        if fulfillment is not None:
            order.destination = fulfillment.destination
            order.pickup_date = fulfillment.pickup_date
            order.pickup_slot = fulfillment.pickup_slot
            order.delivery_recipient_name = fulfillment.delivery_recipient_name
            order.delivery_recipient_phone = fulfillment.delivery_recipient_phone
            order.delivery_address = fulfillment.delivery_address
            order.delivery_date = fulfillment.delivery_date
            order.delivery_slot = fulfillment.delivery_slot
        for item in quote.items if isinstance(quote, CartQuote) else (quote,):
            if item.uploaded_file.checkout_staged_at is not None:
                item.uploaded_file.checkout_staged_at = None
            order.items.append(OrderItem(
                uploaded_file_id=item.uploaded_file.id,
                original_filename=item.uploaded_file.original_filename,
                paper_size=item.paper_size,
                color_mode=item.color_mode,
                quantity=item.quantity,
                pdf_page_count=item.pdf_page_count,
                total_printed_pages=item.total_printed_pages,
                is_rush=item.is_rush,
                unit_price=item.unit_price,
                line_total=item.line_total,
            ))
        if payment_choice is not None:
            selected_method, reference_value = payment_choice
            order.payment = Payment(
                payment_method=selected_method,
                payment_status=(PaymentStatus.SUBMITTED if reference_value else PaymentStatus.PENDING),
                amount=quote.total, currency=quote.currency,
                payment_reference=reference_value,
                submitted_at=utc_now() if reference_value else None,
            )
        db.session.add(order)
        try:
            db.session.commit()
            return order
        except IntegrityError:
            db.session.rollback()
            collision = db.session.scalar(
                select(Order.id).where(Order.order_reference == reference)
            )
            if collision is None:
                raise
    raise RuntimeError("Could not generate a unique order reference.")
