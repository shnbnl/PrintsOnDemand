"""Atomic order creation from a fresh server-side quote."""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Order, OrderItem, OrderStatus
from app.models.user import utc_now
from app.services.pricing import OrderQuote


def create_order(quote: OrderQuote) -> Order:
    """Commit one order and its item, retrying rare reference collisions."""
    for _ in range(5):
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
        order.items.append(OrderItem(
            uploaded_file_id=quote.uploaded_file.id,
            original_filename=quote.uploaded_file.original_filename,
            paper_size=quote.paper_size,
            color_mode=quote.color_mode,
            quantity=quote.quantity,
            is_rush=quote.is_rush,
            unit_price=quote.unit_price,
            line_total=quote.line_total,
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
