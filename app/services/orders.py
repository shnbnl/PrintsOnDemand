"""Atomic order creation from a fresh server-side quote."""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Order, OrderDestination, OrderItem, OrderStatus, Professor, User
from app.models.user import utc_now
from app.services.pricing import CartQuote, OrderQuote
from app.services.professors import assign_professor, validate_professor_selection
from app.services.fulfillment import Fulfillment, FulfillmentError, validate_fulfillment


def create_order(
    quote: CartQuote | OrderQuote, *, destination: str | None = None,
    professor_id: str | int | None = None,
    fulfillment: Fulfillment | None = None,
) -> Order:
    """Commit one order and all quoted items, retrying rare reference collisions."""
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
            order.items.append(OrderItem(
                uploaded_file_id=item.uploaded_file.id,
                original_filename=item.uploaded_file.original_filename,
                paper_size=item.paper_size,
                color_mode=item.color_mode,
                quantity=item.quantity,
                is_rush=item.is_rush,
                unit_price=item.unit_price,
                line_total=item.line_total,
            ))
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
