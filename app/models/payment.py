"""Payment intent and manual verification state, separate from order pricing."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.user import utc_now


class PaymentMethod(StrEnum):
    ONLINE = "ONLINE"
    ONSITE = "ONSITE"


class PaymentStatus(StrEnum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    REJECTED = "REJECTED"


class Payment(db.Model):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_payment_order"),
        CheckConstraint("amount >= 0", name="payment_amount_nonnegative"),
        CheckConstraint(
            "payment_status <> 'SUBMITTED' OR "
            "(payment_method = 'ONLINE' AND payment_reference IS NOT NULL)",
            name="payment_submitted_online_reference",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        db.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    payment_method: Mapped[PaymentMethod] = mapped_column(
        db.Enum(PaymentMethod, name="payment_method", native_enum=False, create_constraint=True),
        nullable=False,
    )
    payment_status: Mapped[PaymentStatus] = mapped_column(
        db.Enum(PaymentStatus, name="payment_status", native_enum=False, create_constraint=True),
        nullable=False, default=PaymentStatus.PENDING,
    )
    amount: Mapped[Decimal] = mapped_column(db.Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(db.String(3), nullable=False)
    payment_reference: Mapped[str | None] = mapped_column(db.String(120), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    reviewed_by_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("users.id", name="fk_payments_reviewed_by_id", ondelete="RESTRICT"),
        nullable=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(db.String(500))
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    order: Mapped[Order] = relationship(back_populates="payment")
    reviewer: Mapped[User | None] = relationship(foreign_keys=[reviewed_by_id])
