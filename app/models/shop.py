"""Printing shops, offered services, and configurable prices."""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, String, UniqueConstraint
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.user import utc_now
from app.services.payment_qr import development_qr


class CoordinateDecimal(TypeDecorator):
    """Store coordinates as exact decimal text across SQLite and SQL databases."""

    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else format(Decimal(value), "f")

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value)


class ServiceType(StrEnum):
    PICKUP = "PICKUP"
    DELIVERY = "DELIVERY"
    DIRECT_TO_PROFESSOR = "DIRECT_TO_PROFESSOR"
    RUSH_PRINTING = "RUSH_PRINTING"

    @property
    def label(self) -> str:
        return {
            self.PICKUP: "Pick-up",
            self.DELIVERY: "Delivery",
            self.DIRECT_TO_PROFESSOR: "Direct-to-Professor",
            self.RUSH_PRINTING: "Rush Printing",
        }[self]


class PaperSize(StrEnum):
    LETTER = "LETTER"
    LEGAL = "LEGAL"
    A4 = "A4"
    A3 = "A3"
    A2 = "A2"

    @property
    def label(self) -> str:
        return self.value.title()


class ColorMode(StrEnum):
    GRAYSCALE = "GRAYSCALE"
    COLOR = "COLOR"

    @property
    def label(self) -> str:
        return {self.GRAYSCALE: "Grayscale", self.COLOR: "Color"}[self]


class FeeType(StrEnum):
    RUSH_PRINTING = "RUSH_PRINTING"
    DELIVERY = "DELIVERY"

    @property
    def label(self) -> str:
        return {self.RUSH_PRINTING: "Rush printing", self.DELIVERY: "Delivery"}[self]


class PrintingShop(db.Model):
    __tablename__ = "printing_shops"
    __table_args__ = (CheckConstraint("opening_time <> closing_time", name="shop_hours_differ"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(db.String(120), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(db.Text, nullable=False, default="")
    address: Mapped[str] = mapped_column(db.String(255), nullable=False)
    latitude: Mapped[Decimal | None] = mapped_column(
        CoordinateDecimal(),
        CheckConstraint("CAST(latitude AS NUMERIC) BETWEEN -90 AND 90", name="shop_latitude_range"),
        nullable=True,
    )
    longitude: Mapped[Decimal | None] = mapped_column(
        CoordinateDecimal(),
        CheckConstraint("CAST(longitude AS NUMERIC) BETWEEN -180 AND 180", name="shop_longitude_range"),
        nullable=True,
    )
    opening_time: Mapped[time] = mapped_column(db.Time, nullable=False)
    closing_time: Mapped[time] = mapped_column(db.Time, nullable=False)
    is_active: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True)
    is_on_break: Mapped[bool] = mapped_column(
        db.Boolean, nullable=False, default=False, server_default=db.false()
    )
    is_demo: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    photo_data: Mapped[bytes | None] = mapped_column(db.LargeBinary, nullable=True, deferred=True)
    photo_mime: Mapped[str | None] = mapped_column(db.String(32), nullable=True)
    photo_digest: Mapped[str | None] = mapped_column(db.String(64), nullable=True)
    cash_enabled: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True)
    online_enabled: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    online_account_name: Mapped[str] = mapped_column(db.String(120), nullable=False, default="")
    online_account_reference: Mapped[str] = mapped_column(db.String(255), nullable=False, default="")
    online_instructions: Mapped[str] = mapped_column(db.Text, nullable=False, default="")
    payment_qr_data: Mapped[bytes | None] = mapped_column(
        db.LargeBinary, nullable=True, deferred=True,
        default=lambda context: development_qr(context.get_current_parameters()["name"])[0],
    )
    payment_qr_mime: Mapped[str | None] = mapped_column(db.String(32), nullable=True, default="image/png")
    payment_qr_digest: Mapped[str | None] = mapped_column(
        db.String(64), nullable=True,
        default=lambda context: development_qr(context.get_current_parameters()["name"])[2],
    )
    created_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    services: Mapped[list[ShopService]] = relationship(
        back_populates="shop", cascade="all, delete-orphan"
    )
    prices: Mapped[list[PrintPrice]] = relationship(
        back_populates="shop", cascade="all, delete-orphan"
    )
    fees: Mapped[list[ShopFee]] = relationship(
        back_populates="shop", cascade="all, delete-orphan"
    )
    staff: Mapped[list[User]] = relationship(back_populates="shop")
    orders: Mapped[list[Order]] = relationship(back_populates="shop")


class ShopService(db.Model):
    __tablename__ = "shop_services"
    __table_args__ = (UniqueConstraint("shop_id", "service_type", name="uq_shop_service"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(
        db.ForeignKey("printing_shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_type: Mapped[ServiceType] = mapped_column(
        db.Enum(ServiceType, name="service_type", native_enum=False, create_constraint=True),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=True)
    shop: Mapped[PrintingShop] = relationship(back_populates="services")


class PrintPrice(db.Model):
    __tablename__ = "print_prices"
    __table_args__ = (
        UniqueConstraint("shop_id", "paper_size", "color_mode", name="uq_shop_print_price"),
        CheckConstraint("price >= 0", name="print_price_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(
        db.ForeignKey("printing_shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    paper_size: Mapped[PaperSize] = mapped_column(
        db.Enum(PaperSize, name="paper_size", native_enum=False, create_constraint=True),
        nullable=False,
    )
    color_mode: Mapped[ColorMode] = mapped_column(
        db.Enum(ColorMode, name="color_mode", native_enum=False, create_constraint=True),
        nullable=False,
    )
    price: Mapped[Decimal] = mapped_column(db.Numeric(10, 2), nullable=False)
    is_demo: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    shop: Mapped[PrintingShop] = relationship(back_populates="prices")


class ShopFee(db.Model):
    __tablename__ = "shop_fees"
    __table_args__ = (
        UniqueConstraint("shop_id", "fee_type", name="uq_shop_fee"),
        CheckConstraint("amount >= 0", name="shop_fee_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(
        db.ForeignKey("printing_shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fee_type: Mapped[FeeType] = mapped_column(
        db.Enum(FeeType, name="fee_type", native_enum=False, create_constraint=True),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(db.Numeric(10, 2), nullable=False)
    is_demo: Mapped[bool] = mapped_column(db.Boolean, nullable=False, default=False)
    shop: Mapped[PrintingShop] = relationship(back_populates="fees")
