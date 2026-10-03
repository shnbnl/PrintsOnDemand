"""Placed orders and immutable checkout snapshots."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.shop import ColorMode, PaperSize
from app.models.user import utc_now


class OrderStatus(StrEnum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PROCESSING = "PROCESSING"
    READY = "READY"
    COMPLETED = "COMPLETED"


class OrderDestination(StrEnum):
    PROFESSOR = "PROFESSOR"
    PICKUP = "PICKUP"
    DELIVERY = "DELIVERY"


class Order(db.Model):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("subtotal >= 0", name="order_subtotal_nonnegative"),
        CheckConstraint("fees_total >= 0", name="order_fees_nonnegative"),
        CheckConstraint("total >= 0", name="order_total_nonnegative"),
        CheckConstraint("rush_fee >= 0", name="order_rush_fee_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    shop_id: Mapped[int] = mapped_column(
        db.ForeignKey("printing_shops.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    order_reference: Mapped[str] = mapped_column(db.String(32), unique=True, nullable=False)
    shop_name: Mapped[str] = mapped_column(db.String(120), nullable=False)
    destination: Mapped[OrderDestination | None] = mapped_column(
        db.Enum(OrderDestination, name="order_destination", native_enum=False, create_constraint=True),
        nullable=True,
    )
    professor_id: Mapped[int | None] = mapped_column(
        db.ForeignKey("professors.id", name="fk_orders_professor_id", ondelete="RESTRICT"),
        nullable=True, index=True
    )
    professor_name: Mapped[str | None] = mapped_column(db.String(120), nullable=True)
    professor_email: Mapped[str | None] = mapped_column(db.String(254), nullable=True)
    professor_department: Mapped[str | None] = mapped_column(db.String(120), nullable=True)
    professor_office: Mapped[str | None] = mapped_column(db.String(120), nullable=True)
    status: Mapped[OrderStatus] = mapped_column(
        db.Enum(OrderStatus, name="order_status", native_enum=False, create_constraint=True),
        nullable=False, default=OrderStatus.PENDING_PAYMENT,
    )
    subtotal: Mapped[Decimal] = mapped_column(db.Numeric(14, 2), nullable=False)
    rush_fee: Mapped[Decimal] = mapped_column(db.Numeric(14, 2), nullable=False, default=Decimal("0.00"))
    fees_total: Mapped[Decimal] = mapped_column(db.Numeric(14, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(db.Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(db.String(3), nullable=False, default="PHP")
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    processing_started_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="orders")
    shop: Mapped[PrintingShop] = relationship(back_populates="orders")
    professor: Mapped[Professor | None] = relationship(back_populates="orders")
    payment: Mapped[Payment | None] = relationship(back_populates="order", uselist=False)
    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.id"
    )


class OrderItem(db.Model):
    __tablename__ = "order_items"
    __table_args__ = (
        UniqueConstraint("order_id", "uploaded_file_id", name="uq_order_item_file"),
        CheckConstraint("quantity >= 1", name="order_item_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="order_item_unit_price_nonnegative"),
        CheckConstraint("line_total >= 0", name="order_item_line_total_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        db.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploaded_file_id: Mapped[int] = mapped_column(
        db.ForeignKey("uploaded_files.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    original_filename: Mapped[str] = mapped_column(db.String(255), nullable=False)
    paper_size: Mapped[PaperSize] = mapped_column(
        db.Enum(PaperSize, name="paper_size", native_enum=False, create_constraint=True), nullable=False
    )
    color_mode: Mapped[ColorMode] = mapped_column(
        db.Enum(ColorMode, name="color_mode", native_enum=False, create_constraint=True), nullable=False
    )
    quantity: Mapped[int] = mapped_column(db.Integer, nullable=False)
    is_rush: Mapped[bool] = mapped_column(db.Boolean, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(db.Numeric(14, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(db.Numeric(14, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    order: Mapped[Order] = relationship(back_populates="items")
    uploaded_file: Mapped[UploadedFile] = relationship(back_populates="order_items")
