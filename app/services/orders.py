"""Atomic order creation from a fresh server-side quote."""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Order, OrderItem, OrderStatus
from app.models.user import utc_now
from app.services.pricing import CartQuote, OrderQuote
from app.services.professors import assign_professor, validate_professor_selection


def create_order(
    quote: CartQuote | OrderQuote, *, destination: str | None = None,
    professor_id: str | int | None = None,
) -> Order:
    """Commit one order and all quoted items, retrying rare reference collisions."""
    for _ in range(5):
        professor = validate_professor_selection(
            shop_id=quote.shop.id, destination=destination, professor_id=professor_id
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
            fees_total=quote.fees_total,
            total=quote.total,
            currency=quote.currency,
        )
        if professor is not None:
            assign_professor(order, professor)
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
